"""Actual Windows PowerShell parsing and fail-before-network source protection."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
PS = shutil.which('powershell.exe')


@pytest.mark.skipif(not PS, reason='Windows PowerShell 5.1 required')
def test_entry_is_utf8_bom_and_parses_in_windows_powershell():
    script = ROOT / 'scripts/mobile-128-entry.ps1'
    assert script.read_bytes().startswith(b'\xef\xbb\xbf')
    code = "$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$t,[ref]$e);if($e){$e;exit 1}"
    # File argument supplied through a small script instead of -Command positional parsing.
    result = subprocess.run([PS, '-NoProfile', '-Command',
        code.replace('$args[0]', "'" + str(script).replace("'", "''") + "'")], capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not PS, reason='Windows PowerShell 5.1 required')
def test_changed_commit_stops_before_cloud_even_in_all_mode(tmp_path):
    info = tmp_path / 'delivery.json'
    info.write_text(json.dumps({'ProjectRoot': str(ROOT), 'SourceCommit': '0' * 40}), encoding='utf-8')
    harness = tmp_path / 'test.ps1'
    harness.write_text('''$ErrorActionPreference='Stop'
function ssh.exe { throw 'NETWORK_FORBIDDEN' }
function scp.exe { throw 'NETWORK_FORBIDDEN' }
& $args[0] -Mode all -DeliveryInfoPath $args[1]
''', encoding='utf-8-sig')
    result = subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness),
                             str(ROOT / 'scripts/mobile-128-entry.ps1'), str(info)], capture_output=True)
    assert result.returncode != 0
    assert b'NETWORK_FORBIDDEN' not in result.stdout + result.stderr
    assert b'Delivered source changed' in result.stderr
