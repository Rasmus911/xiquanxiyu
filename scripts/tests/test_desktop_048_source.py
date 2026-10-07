"""Source identity checks run against actual staged bytes before deployment."""
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))


def staged(tmp_path):
    deploy = importlib.import_module('desktop_048_deploy')
    source = tmp_path / 'xiquan'
    files = {'client/package.json': b'{"version":"0.4.8"}',
             'server/app/stock_cost_service.py': b'# reviewed costs\n',
             'server/migrations/versions/20261007_ordering_cost.py': b'# reviewed migration\n'}
    for name in deploy.TOOLS:
        files['deploy/cloud/scripts/' + name] = (ROOT / 'deploy/cloud/scripts' / name).read_bytes()
    records = []
    for name, content in files.items():
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        records.append({'file': name, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    (source / 'source-manifest.json').write_text(json.dumps({'source_commit': 'a' * 40, 'files': records}))
    return deploy, source


def test_reviewed_source_uses_exact_transport_bytes_and_desktop_version(tmp_path):
    deploy, source = staged(tmp_path)
    assert callable(getattr(deploy, 'verify_source', None)), '0.4.8 SOURCE verification missing'
    assert deploy.verify_source(source)['source_commit'] == 'a' * 40


@pytest.mark.parametrize('changed', ('client/package.json', 'deploy/cloud/scripts/desktop_048_guard.py',
                                  'server/migrations/versions/20261007_ordering_cost.py'))
def test_rejects_altered_renderer_transport_or_migration_even_with_rewritten_manifest(tmp_path, changed):
    deploy, source = staged(tmp_path)
    assert callable(getattr(deploy, 'verify_source', None)), '0.4.8 SOURCE verification missing'
    candidate = source / changed
    candidate.write_bytes(b'{"version":"0.4.7"}' if changed.endswith('package.json') else b'# changed\n')
    manifest = json.loads((source / 'source-manifest.json').read_text())
    if changed.endswith('package.json') or changed.endswith('desktop_048_guard.py'):
        record = next(row for row in manifest['files'] if row['file'] == changed)
        record.update(size=candidate.stat().st_size, sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
        (source / 'source-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(deploy.DeploymentError):
        deploy.verify_source(source)
