"""Bounded real child processes and SSH payload byte/hash verification."""
import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
PS = shutil.which('powershell.exe')
LIB = ROOT / 'scripts/lib/mobile-128-transport.ps1'
PYTHON = ROOT / 'server/.venv/Scripts/python.exe'


def harness(tmp_path, code):
    script = tmp_path / 'harness.ps1'
    script.write_text("$ErrorActionPreference='Stop'\n. '" + str(LIB) + "'\n" + code, encoding='utf-8-sig')
    return subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                          capture_output=True, timeout=20)


@pytest.mark.skipif(not PS, reason='Windows PowerShell required')
def test_child_stalled_after_printing_100_percent_stops_at_total_deadline(tmp_path):
    child = tmp_path / 'hang.ps1'
    child.write_text("Write-Output '100%'; Start-Sleep -Seconds 60", encoding='utf-8-sig')
    result = harness(tmp_path, """
try {
  Invoke-TokenNative -Executable 'powershell.exe' -Arguments @('-NoProfile','-ExecutionPolicy','Bypass','-File','%s') -TimeoutSeconds 1 -Label 'UPLOAD'
  throw 'DEADLINE_NOT_ENFORCED'
} catch {
  if($_.Exception.Message -notmatch 'TOKEN_TRANSPORT_TIMEOUT') { throw }
  'TIMED_OUT_WITHOUT_CONTINUING'
}
""" % str(child))
    assert result.returncode == 0, result.stderr
    assert b'TIMED_OUT_WITHOUT_CONTINUING' in result.stdout


@pytest.mark.skipif(not PS, reason='Windows PowerShell required')
def test_native_argument_spaces_quotes_and_trailing_slash_are_preserved(tmp_path):
    code = "import sys,json;print(json.dumps(sys.argv[1:]))"
    result = harness(tmp_path, """
$result = Invoke-TokenNative -Executable '%s' -Arguments @('-c','%s','path with spaces','a"b','C:\\task\\') -TimeoutSeconds 5 -Label 'ARGS'
$result.Stdout
""" % (str(PYTHON), code))
    assert result.returncode == 0, result.stderr
    import json
    assert json.loads(result.stdout.strip()) == ['path with spaces', 'a"b', 'C:\\task\\']


@pytest.mark.skipif(not PS, reason='Windows PowerShell required')
def test_upload_payload_reproduces_exact_bytes_and_hash_on_remote_python(tmp_path):
    data = b'\x00\xff\r\n' + '注册令牌'.encode('utf-8')
    local = tmp_path / 'source.bin'; local.write_bytes(data)
    result = harness(tmp_path, "New-TokenUploadProgram -LocalPath '%s' -RemotePath '/tmp/xiquan-token128-%s/mobile.py'" % (str(local), 'a' * 32))
    assert result.returncode == 0, result.stderr
    # Run the production-generated program in an isolated local temp directory.
    # Only substitute the validated remote destination to avoid writing /tmp on Windows.
    program = result.stdout.decode('utf-8-sig')
    destination = tmp_path / 'mobile.py'
    program = program.replace("'/tmp/xiquan-token128-" + 'a' * 32 + "/mobile.py'", repr(str(destination)))
    uploaded = subprocess.run([str(PYTHON), '-'], input=program.encode('utf-8'), capture_output=True, timeout=10)
    assert uploaded.returncode == 0, uploaded.stderr
    assert destination.read_bytes() == data
    assert hashlib.sha256(data).hexdigest().encode() in uploaded.stdout


@pytest.mark.skipif(not PS, reason='Windows PowerShell required')
@pytest.mark.parametrize('remote', ['/opt/xiquan/mobile.py','/tmp/xiquan-token128-' + 'a' * 32 + '/../mobile.py'])
def test_upload_rejects_out_of_scope_path_before_creating_program(tmp_path, remote):
    local = tmp_path / 'local.py'; local.write_bytes(b'pass\n')
    result = harness(tmp_path, "New-TokenUploadProgram -LocalPath '%s' -RemotePath '%s'" % (str(local), remote))
    assert result.returncode != 0
    assert b'Invalid upload destination' in result.stderr


@pytest.mark.skipif(not PS, reason='Windows PowerShell required')
def test_input_is_written_fully_and_eof_delivered_to_real_python(tmp_path):
    result = harness(tmp_path, """
$inputProgram = "payload = '" + ('x' * 200000) + "'`nprint(len(payload))`n"
$result = Invoke-TokenNative -Executable '%s' -Arguments @('-') -InputText $inputProgram -TimeoutSeconds 5 -Label 'STDIN'
if($result.ExitCode -ne 0) { throw $result.Stderr }
$result.Stdout
""" % str(PYTHON))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == b'200000'


@pytest.mark.skipif(not PS, reason='Windows PowerShell required')
def test_peer_not_reading_input_cannot_block_the_deadline(tmp_path):
    result = harness(tmp_path, """
try {
  Invoke-TokenNative -Executable '%s' -Arguments @('-c','import time;time.sleep(60)') -InputText ('x' * 1000000) -TimeoutSeconds 1 -Label 'BLOCKED_INPUT'
  throw 'DEADLINE_NOT_ENFORCED'
} catch {
  if($_.Exception.Message -notmatch 'TOKEN_TRANSPORT_TIMEOUT') { throw }
  'BLOCKED_INPUT_TIMED_OUT'
}
""" % str(PYTHON))
    assert result.returncode == 0, result.stderr
    assert b'BLOCKED_INPUT_TIMED_OUT' in result.stdout
