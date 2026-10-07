"""Run PowerShell entrypoints locally; transport and signing stay fixture-only."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which('pwsh')


def script(name):
    path = ROOT / 'scripts' / name
    assert path.is_file(), f'{name} entrypoint missing'
    return path


def invoke(tmp_path, *, bad_tool=False, wrong_commit=False, wrong_hash=False):
    path = script('invoke-desktop-048.ps1')
    names = ('desktop_048_deploy.py', 'desktop_048_guard.py', 'stock_deploy.py', 'stock_guard.py',
             'operations_backup_verify.py', 'operations_preflight.py', 'operations_deploy.py', 'operations_offline_build.py')
    records = [{'file': 'deploy/cloud/scripts/' + name,
                'sha256': hashlib.sha256((ROOT / 'deploy/cloud/scripts' / name).read_bytes()).hexdigest()} for name in names]
    if bad_tool:
        records[0]['sha256'] = 'b' * 64
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('xiquan/source-manifest.json', json.dumps({'source_commit': 'a' * 40, 'files': records}))
    digest = 'f' * 64 if wrong_hash else hashlib.sha256(archive.read_bytes()).hexdigest()
    return subprocess.run([PWSH, '-NoProfile', '-File', str(path), '-StageOnly', '-BundlePath', str(archive),
                           '-ExpectedSha256', digest, '-SourceCommit', ('c' if wrong_commit else 'a') * 40],
                          capture_output=True, text=True, encoding='utf-8', timeout=30)


@pytest.mark.skipif(not PWSH, reason='PowerShell required')
def test_stageonly_verifies_exact_local_tool_and_bundle_identity_without_connecting(tmp_path):
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    assert 'False' in result.stdout


@pytest.mark.skipif(not PWSH, reason='PowerShell required')
@pytest.mark.parametrize('failure', ('bad_tool', 'wrong_commit', 'wrong_hash'))
def test_transport_entrypoint_rejects_mismatched_identity_before_connection(tmp_path, failure):
    result = invoke(tmp_path, **{failure: True})
    assert result.returncode != 0
    assert ('Transport differs' if failure == 'bad_tool' else 'mismatch') in result.stderr


@pytest.mark.skipif(not PWSH, reason='PowerShell required')
def test_signing_wrapper_preserves_live_plan_sequence_and_each_target_minimum(tmp_path):
    source = script('sign-desktop-048.ps1')
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    (scripts / 'lib').mkdir()
    wrapper = scripts / source.name
    shutil.copyfile(source, wrapper)
    release = tmp_path / 'release'
    release.mkdir()
    signer = scripts / 'sign-windows-release.ps1'
    signer.write_text('''param($ReleaseRoot,$PrivateKeyPath,$Sequence,$MinimumVersion,$Targets,$ReleaseNotes)
[pscustomobject]@{sequence=$Sequence;minimum=$MinimumVersion;target=$Targets[0]} |
    ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $ReleaseRoot 'calls.jsonl')
''', encoding='utf-8')
    command = '''function node.exe {
    $global:LASTEXITCODE=0
    if($args[1] -eq 'plan') {
        if($args[2] -cne '0.4.8'){throw 'Wrong requested desktop version'}
        '{"sequence":92,"previous":[{"target":"win10-x86","minimum_version":"0.4.2"},{"target":"win10-x64","minimum_version":"0.4.3"},{"target":"win11-x86","minimum_version":"0.4.4"},{"target":"win11-x64","minimum_version":"0.4.5"}]}'
    } elseif($args[1] -eq 'verify-candidates') {
        if($args[3] -cne '0.4.8'){throw 'Wrong candidate version'}
    } else {throw 'Unexpected external command'}
}
& $args[0] -ReleaseRoot $args[1] -PrivateKeyPath 'fixture-only-never-read'
'''
    harness = tmp_path / 'run.ps1'
    harness.write_text(command, encoding='utf-8')
    result = subprocess.run([PWSH, '-NoProfile', '-File', str(harness), str(wrapper), str(release)],
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (release / 'calls.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert calls == [{'sequence': 92, 'minimum': version, 'target': target} for target, version in
                     [('win10-x86', '0.4.2'), ('win10-x64', '0.4.3'), ('win11-x86', '0.4.4'), ('win11-x64', '0.4.5')]]
