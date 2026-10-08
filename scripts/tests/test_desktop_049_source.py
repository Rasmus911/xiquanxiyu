"""Actual staged source bytes and allowlist inclusion."""
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))


def staged(tmp_path):
    assert (ROOT / 'deploy/cloud/scripts/desktop_049_deploy.py').exists(), 'Registration deployment missing'
    deploy = importlib.import_module('desktop_049_deploy')
    source = tmp_path / 'xiquan'
    files = {'client/package.json': b'{"version":"0.4.9"}',
             'mobile/version.json': b'{"version":"1.2.7","versionCode":14}',
             'server/app/registration_service.py': b'# reviewed registration\n',
             'server/migrations/versions/20261008_registration_token.py': b'# additive migration\n'}
    for name in deploy.TOOLS:
        files['deploy/cloud/scripts/' + name] = (ROOT / 'deploy/cloud/scripts' / name).read_bytes()
    records = []
    for name, content in files.items():
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        records.append(dict(file=name, size=len(content), sha256=hashlib.sha256(content).hexdigest()))
    (source / 'source-manifest.json').write_text(json.dumps(dict(source_commit='a' * 40, files=records)))
    return deploy, source


def test_exact_source_and_transported_tools(tmp_path):
    deploy, source = staged(tmp_path)
    assert deploy.verify_source(source)['source_commit'] == 'a' * 40


@pytest.mark.parametrize('file', ['client/package.json', 'server/app/registration_service.py', 'deploy/cloud/scripts/desktop_049_guard.py'])
def test_altered_bytes_fail_closed(tmp_path, file):
    deploy, source = staged(tmp_path)
    (source / file).write_bytes(b'changed')
    with pytest.raises(deploy.DeploymentError):
        deploy.verify_source(source)


def test_public_source_enumeration_includes_all_release_tools():
    names = ['scripts/build-desktop-049.ps1', 'scripts/sign-desktop-049.ps1', 'scripts/invoke-desktop-049.ps1',
             'deploy/cloud/scripts/desktop_049_guard.py', 'deploy/cloud/scripts/desktop_049_deploy.py',
             'deploy/cloud/scripts/android_127_publication.py']
    result = subprocess.run(['node', '-e', 'const s=require("./scripts/lib/source-security.cjs");console.log(JSON.stringify(process.argv.slice(1).map(x=>s.allowed(x))))', *names], cwd=ROOT, capture_output=True, text=True)
    assert json.loads(result.stdout) == [True] * len(names)
