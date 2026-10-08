"""Windows PowerShell 5.1 child-process tests with network boundary traps."""
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PS = shutil.which('powershell.exe')
TOOLS = ('desktop_049_deploy.py', 'desktop_049_guard.py', 'stock_deploy.py', 'stock_guard.py',
         'operations_backup_verify.py', 'operations_preflight.py', 'operations_deploy.py', 'operations_offline_build.py')


def bundle(tmp_path, bad=''):
    files = {'deploy/cloud/scripts/' + n: (ROOT / 'deploy/cloud/scripts' / n).read_bytes() for n in TOOLS}
    files.update({'client/package.json': b'{"version":"0.4.9"}', 'mobile/version.json': b'{"version":"1.2.7","versionCode":14}',
                  'server/app/registration_service.py': b'# registration', 'server/migrations/versions/20261008_registration_token.py': b'# additive'})
    records = [dict(file=n, size=len(b), sha256=hashlib.sha256(b).hexdigest()) for n, b in files.items()]
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        for n, b in files.items():
            zipped.writestr('xiquan/' + n, b'changed' if bad == 'bytes' and n.endswith('registration_service.py') else b)
        zipped.writestr('xiquan/source-manifest.json', json.dumps(dict(source_commit='a' * 40, files=records)))
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


@pytest.mark.skipif(not PS, reason='Actual Windows PowerShell required')
@pytest.mark.parametrize('bad', ['', 'bytes', 'hash', 'commit'])
def test_stageonly_verifies_bundle_without_ssh(tmp_path, bad):
    script = ROOT / 'scripts/invoke-desktop-049.ps1'
    assert script.exists(), 'Registration entrypoint missing'
    archive, digest = bundle(tmp_path, bad)
    harness = tmp_path / 'harness.ps1'
    harness.write_text('function ssh.exe { throw "NETWORK_FORBIDDEN" }; function scp.exe { throw "NETWORK_FORBIDDEN" }; & $args[0] -StageOnly -BundlePath $args[1] -ExpectedSha256 $args[2] -SourceCommit $args[3]', encoding='utf-8-sig')
    result = subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness), str(script), str(archive), 'f' * 64 if bad == 'hash' else digest, ('b' if bad == 'commit' else 'a') * 40], capture_output=True, text=True, encoding='utf-8', timeout=40)
    assert 'NETWORK_FORBIDDEN' not in result.stderr
    assert (result.returncode == 0) == (not bad), result.stderr
    if not bad:
        assert 'False' in result.stdout


@pytest.mark.skipif(not PS, reason='Actual Windows PowerShell required')
@pytest.mark.parametrize('wrong_stage_identity', [False, True])
def test_all_mode_parses_verified_private_stage_automatically(tmp_path, wrong_stage_identity):
    archive, digest = bundle(tmp_path)
    harness = tmp_path / 'remote-boundary.ps1'
    harness.write_text('''$ErrorActionPreference='Stop'
$global:fixtureRemoteFiles=@{}
$global:fixtureExpected=$args[2]
$global:fixtureCommit=$args[3]
$global:fixtureWrong=$args[4]
function scp.exe { $global:fixtureRemoteFiles[($args[-1] -split ':',2)[1]]=(Get-FileHash -LiteralPath $args[-2] -Algorithm SHA256).Hash.ToLowerInvariant(); $global:LASTEXITCODE=0 }
function ssh.exe {
 $global:LASTEXITCODE=0; $command=$args[-1]
 if($command.StartsWith('sha256sum ')){foreach($file in ($command.Substring(10) -split ' ')){ $global:fixtureRemoteFiles[$file]+'  '+$file };return}
 if($command -match ' preflight '){
   $sha=$global:fixtureExpected; if($global:fixtureWrong-eq 'yes'){$sha='f'*64}
   @{stage=('/opt/xiquan-releases/desktop049-stage-'+('a'*32));source_commit=$global:fixtureCommit;source_sha256=$sha}|ConvertTo-Json -Compress;return
 }
 if($command -match ' deploy '){Write-Output ('DEPLOY_CALL='+$command);return}
 if(-not $command.StartsWith('umask 077')){throw 'Unexpected transport command'}
}
function Read-Host { 'UPDATE 0.4.9' }
& $args[0] -Mode all -BundlePath $args[1] -ExpectedSha256 $args[2] -SourceCommit $args[3]
''', encoding='utf-8-sig')
    result = subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness),
                             str(ROOT / 'scripts/invoke-desktop-049.ps1'), str(archive), digest, 'a' * 40,
                             'yes' if wrong_stage_identity else 'no'], capture_output=True, text=True, encoding='utf-8', timeout=40)
    assert (result.returncode == 0) == (not wrong_stage_identity), result.stderr
    if wrong_stage_identity:
        assert 'DEPLOY_CALL=' not in result.stdout
    else:
        assert '--stage /opt/xiquan-releases/desktop049-stage-' + 'a' * 32 in result.stdout


@pytest.mark.skipif(not PS, reason='Actual Windows PowerShell required')
def test_signing_wrapper_preserves_verified_sequence_minima_and_exact_note(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    (scripts / 'lib').mkdir()
    wrapper = scripts / 'sign-desktop-049.ps1'
    shutil.copyfile(ROOT / 'scripts/sign-desktop-049.ps1', wrapper)
    release = tmp_path / 'release'
    release.mkdir()
    (scripts / 'sign-windows-release.ps1').write_text('''param($ReleaseRoot,$PrivateKeyPath,$Sequence,$MinimumVersion,$Targets,$ReleaseNotes)
@{sequence=$Sequence;minimum=$MinimumVersion;target=$Targets[0];notes=$ReleaseNotes} | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $ReleaseRoot 'calls.jsonl') -Encoding UTF8
''', encoding='utf-8-sig')
    harness = tmp_path / 'sign-boundary.ps1'
    harness.write_text('''function node.exe {
 $global:LASTEXITCODE=0
 if($args[1]-eq 'plan'){
   if($args[2]-cne '0.4.9'){throw 'Wrong version'}
   '{"sequence":92,"previous":[{"target":"win10-x86","minimum_version":"0.4.2"},{"target":"win10-x64","minimum_version":"0.4.3"},{"target":"win11-x86","minimum_version":"0.4.4"},{"target":"win11-x64","minimum_version":"0.4.5"}]}'
 } elseif($args[1]-ne 'verify-candidates'){throw 'Unexpected node command'}
}
& $args[0] -ReleaseRoot $args[1] -PrivateKeyPath 'fixture-only-never-read'
''', encoding='utf-8-sig')
    result = subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness), str(wrapper), str(release)], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (release / 'calls.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert calls == [dict(sequence=92, minimum=version, target=target, notes=['新增 账号注册功能']) for target, version in
                     [('win10-x86', '0.4.2'), ('win10-x64', '0.4.3'), ('win11-x86', '0.4.4'), ('win11-x64', '0.4.5')]]


@pytest.mark.skipif(not PS, reason='Actual Windows PowerShell required')
def test_new_scripts_parse_as_windows_powershell_and_keep_chinese_bom(tmp_path):
    names = ['build-desktop-049.ps1', 'sign-desktop-049.ps1', 'invoke-desktop-049.ps1',
             'desktop-049-deploy-entry.ps1', 'desktop-049-publish-entry.ps1', 'desktop-049-android-entry.ps1']
    for name in names:
        assert (ROOT / 'scripts' / name).read_bytes().startswith(b'\xef\xbb\xbf')
    harness = tmp_path / 'parse.ps1'
    harness.write_text('''$ErrorActionPreference='Stop'
foreach($file in $args){$tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$errors);if($errors.Count){throw ($errors|Out-String)}}
Write-Output 'PS51_PARSE_OK'
''', encoding='utf-8-sig')
    result = subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness), *[str(ROOT / 'scripts' / n) for n in names]], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
