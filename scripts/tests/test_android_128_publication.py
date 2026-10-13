"""Registration-token mobile update preserves desktop/web policies and APK identity."""
import copy
import importlib
import sys
from pathlib import Path
import json
import zipfile
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))


def inputs():
    return ({'schemaVersion': 1, 'desktop': {'latestVersion': '0.4.9', 'retained': True},
             'web': {'retained': True}, 'android': {'latestVersion': '1.2.7',
             'latestVersionCode': 14, 'minimumVersionCode': 9}},
            {'version': '1.2.8', 'versionCode': 15, 'minimumVersionCode': 9,
             'androidApkUrl': '/mobile/downloads/xiquan-mobile-ordering-1.2.8.apk',
             'sha256': 'a' * 64, 'releaseNotes': '手机底部新增 注册令牌\n修复同步后令牌入口消失'})


def test_policy_preserves_desktop_web_and_announces_only_android_128():
    p = importlib.import_module('android_128_publication')
    previous, config = inputs()
    unchanged = copy.deepcopy(previous)
    result = p.merge_policy(previous, config)
    assert previous == unchanged
    assert result['desktop'] == previous['desktop']
    assert result['web'] == previous['web']
    assert result['android']['latestVersionCode'] == 15
    assert result['android']['latestVersion'] == '1.2.8'
    assert result['android']['minimumVersionCode'] == 9
    assert result['android']['downloadUrl'] == 'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.2.8.apk'


def test_installer_fix_129_advances_android_without_changing_desktop_or_minimum():
    p = importlib.import_module('android_128_publication')
    previous, config = inputs()
    previous['android'].update(latestVersion='1.2.8', latestVersionCode=15, sha256='b' * 64)
    config.update(version='1.2.9', versionCode=16,
                  androidApkUrl='/mobile/downloads/xiquan-mobile-ordering-1.2.9.apk',
                  releaseNotes='修复应用内更新无法打开系统安装器')
    result = p.merge_policy(previous, config)
    assert result['desktop'] == previous['desktop']
    assert result['web'] == previous['web']
    assert result['android']['latestVersion'] == '1.2.9'
    assert result['android']['latestVersionCode'] == 16
    assert result['android']['minimumVersionCode'] == 9
    assert result['android']['downloadUrl'] == 'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.2.9.apk'


@pytest.mark.parametrize('mutation', ['wrong_code', 'wrong_url', 'same_code', 'newer'])
def test_installer_fix_129_rejects_mismatched_or_immutable_version(mutation):
    p = importlib.import_module('android_128_publication')
    previous, config = inputs()
    config.update(version='1.2.9', versionCode=16,
                  androidApkUrl='/mobile/downloads/xiquan-mobile-ordering-1.2.9.apk')
    if mutation == 'wrong_code': config['versionCode'] = 15
    if mutation == 'wrong_url': config['androidApkUrl'] = '/mobile/downloads/xiquan-mobile-ordering-1.2.8.apk'
    if mutation == 'same_code': previous['android'].update(latestVersion='1.2.9', latestVersionCode=16, sha256='b' * 64)
    if mutation == 'newer': previous['android']['latestVersionCode'] = 17
    with pytest.raises(ValueError): p.merge_policy(previous, config)


@pytest.mark.parametrize('mutation', ['version', 'code', 'url', 'hash', 'newer', 'same_code', 'minimum'])
def test_policy_rejects_mismatched_downgraded_or_mutated_android_release(mutation):
    p = importlib.import_module('android_128_publication')
    previous, config = inputs()
    if mutation == 'version': config['version'] = '1.2.7'
    if mutation == 'code': config['versionCode'] = 14
    if mutation == 'url': config['androidApkUrl'] = '/mobile/downloads/other.apk'
    if mutation == 'hash': config['sha256'] = 'invalid'
    if mutation == 'newer': previous['android']['latestVersionCode'] = 16
    if mutation == 'same_code': previous['android'].update(latestVersion='1.2.8', latestVersionCode=15, sha256='b' * 64)
    if mutation == 'minimum': previous['android']['minimumVersionCode'] = 10
    with pytest.raises(ValueError): p.merge_policy(previous, config)


def web_tree(root):
    root.mkdir()
    (root / 'assets').mkdir()
    (root / 'index.html').write_text('<script src="./assets/app.js"></script>', encoding='utf-8')
    (root / 'assets/app.js').write_text('const label = "注册令牌"', encoding='utf-8')
    (root / 'download-config.json').write_text('{"keep":"out"}', encoding='utf-8')
    return root


def test_mobile_web_replacement_keeps_old_assets_downloads_and_config(tmp_path):
    p = importlib.import_module('android_128_publication')
    incoming = web_tree(tmp_path / 'incoming')
    live = tmp_path / 'live'; live.mkdir()
    (live / 'assets').mkdir(); (live / 'assets/old.js').write_text('retained')
    (live / 'downloads').mkdir(); (live / 'downloads/old.apk').write_bytes(b'old apk')
    (live / 'download-config.json').write_text('{"old":true}')
    (live / 'index.html').write_text('old index')
    backup = tmp_path / 'backup'; backup.mkdir()
    p.publish_mobile_web(incoming, live, backup)
    assert (live / 'index.html').read_text() == (incoming / 'index.html').read_text()
    assert (live / 'assets/app.js').read_text(encoding='utf-8') == (incoming / 'assets/app.js').read_text(encoding='utf-8')
    assert (live / 'assets/old.js').read_text() == 'retained'
    assert (live / 'downloads/old.apk').read_bytes() == b'old apk'
    assert json.loads((live / 'download-config.json').read_text()) == {'old': True}
    assert (backup / 'web/index.html').read_text() == 'old index'


@pytest.mark.parametrize('bad_name', ['private.env', 'server.py', 'downloads/new.apk'])
def test_mobile_web_invalid_tree_stops_before_any_live_file_changes(tmp_path, bad_name):
    p = importlib.import_module('android_128_publication')
    incoming = web_tree(tmp_path / 'incoming')
    bad = incoming / bad_name; bad.parent.mkdir(parents=True, exist_ok=True); bad.write_text('bad')
    live = tmp_path / 'live'; live.mkdir(); (live / 'index.html').write_text('old')
    backup = tmp_path / 'backup'; backup.mkdir()
    with pytest.raises(ValueError): p.publish_mobile_web(incoming, live, backup)
    assert (live / 'index.html').read_text() == 'old'


@pytest.mark.parametrize('bad_name', ['../outside.js', '..\\outside.js', '/absolute.js', 'downloads/app.apk', 'private.env'])
def test_web_archive_rejects_unsafe_members_before_extraction(tmp_path, bad_name):
    p = importlib.import_module('android_128_publication')
    archive = tmp_path / 'web.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('index.html', '<script src="./assets/app.js"></script>')
        zipped.writestr(bad_name, 'bad')
    destination = tmp_path / 'expanded'
    with pytest.raises(ValueError): p.extract_web_archive(archive, destination)
    assert not destination.exists()


def test_web_archive_extracts_only_valid_small_public_files(tmp_path):
    p = importlib.import_module('android_128_publication')
    archive = tmp_path / 'web.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('index.html', '<script src="./assets/app.js"></script>')
        zipped.writestr('assets/app.js', 'const label="注册令牌"')
    destination = tmp_path / 'expanded'
    p.extract_web_archive(archive, destination)
    assert (destination / 'index.html').is_file()
    assert (destination / 'assets/app.js').read_text(encoding='utf-8') == 'const label="注册令牌"'


@pytest.mark.skipif(not shutil.which('powershell.exe'), reason='Windows PowerShell archive implementation required')
def test_real_windows_compress_archive_is_accepted_by_linux_publisher(tmp_path, monkeypatch):
    p = importlib.import_module('android_128_publication')
    web = web_tree(tmp_path / 'web')
    archive = tmp_path / 'web.zip'
    command = "Compress-Archive -LiteralPath @('" + str(web / 'index.html') + "','" + str(web / 'assets') + "') -DestinationPath '" + str(archive) + "'"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command], capture_output=True)
    assert result.returncode == 0, result.stderr
    destination = tmp_path / 'expanded'
    monkeypatch.setattr(zipfile.os, 'sep', '/')
    p.extract_web_archive(archive, destination)
    assert (destination / 'assets/app.js').is_file()


def test_windows_backslash_entries_are_normalized_safely(tmp_path, monkeypatch):
    p = importlib.import_module('android_128_publication')
    archive = tmp_path / 'windows.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('index.html', '<script src="./assets/app.js"></script>')
        entry = zipfile.ZipInfo('assets/app.js')
        entry.filename = 'assets\\app.js'
        zipped.writestr(entry, 'const token = true')
    destination = tmp_path / 'expanded'
    # Linux ZipInfo does not silently replace Windows separators on read.
    monkeypatch.setattr(zipfile.os, 'sep', '/')
    p.extract_web_archive(archive, destination)
    assert (destination / 'assets/app.js').is_file()
