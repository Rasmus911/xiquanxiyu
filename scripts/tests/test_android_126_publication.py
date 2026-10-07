"""Android 1.2.6 discovery must preserve existing feeds and immutable installers."""
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))


def module():
    assert (ROOT / 'deploy/cloud/scripts/android_126_publication.py').is_file(), 'Android 1.2.6 publisher missing'
    return importlib.import_module('android_126_publication')


def fixture():
    return ({'schemaVersion': 1, 'desktop': {'latestVersion': '0.4.7', 'signature': 'kept'},
             'web': {'buildId': 'kept'}, 'android': {'latestVersion': '1.2.5', 'latestVersionCode': 12, 'minimumVersionCode': 9}},
            {'version': '1.2.6', 'versionCode': 13, 'minimumVersionCode': 9,
             'androidApkUrl': '/mobile/downloads/xiquan-mobile-ordering-1.2.6.apk',
             'sha256': 'a' * 64, 'releaseNotes': '手机同步'})


def test_merge_advances_android_only_and_preserves_previous_minimum():
    pub = module()
    old, config = fixture()
    old['android']['minimumVersionCode'] = 10
    updated = pub.merge_policy(old, config)
    assert updated['desktop'] == old['desktop'] and updated['web'] == old['web']
    assert updated['android']['latestVersion'] == '1.2.6'
    assert updated['android']['latestVersionCode'] == 13
    assert updated['android']['minimumVersionCode'] == 10
    assert old['android']['latestVersionCode'] == 12


@pytest.mark.parametrize('field,value', (('version', '1.2.5'), ('versionCode', 12),
                                      ('minimumVersionCode', 8), ('sha256', 'bad'),
                                      ('androidApkUrl', '/mobile/downloads/old.apk')))
def test_rejects_wrong_candidate_identity(field, value):
    pub = module()
    old, config = fixture()
    config[field] = value
    with pytest.raises(ValueError):
        pub.merge_policy(old, config)


def test_rejects_downgrade_and_same_version_different_apk():
    pub = module()
    old, config = fixture()
    old['android']['latestVersionCode'] = 14
    with pytest.raises(ValueError):
        pub.merge_policy(old, config)
    old['android'].update(latestVersion='1.2.6', latestVersionCode=13, sha256='b' * 64)
    with pytest.raises(ValueError):
        pub.merge_policy(old, config)


def test_publication_retains_all_old_apks_desktop_and_web_bytes(tmp_path, monkeypatch):
    pub = module()
    old, config = fixture()
    cloud = tmp_path / 'cloud'
    backups = tmp_path / 'backups'
    backups.mkdir()
    retained = {'mobile/downloads/old.apk': b'old installer',
                'updates/win10-x64/latest.yml': b'old desktop feed',
                'releases/desktop/win10-x64.json': b'original desktop signature',
                'web/version.json': b'old web feed'}
    for name, content in retained.items():
        target = cloud / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    policy = cloud / 'releases/client-policy.json'
    policy.write_text(json.dumps(old))
    incoming = tmp_path / 'incoming.apk'
    incoming.write_bytes(b'fixture-apk' * 120000)
    config['sha256'] = pub.file_hash(incoming)
    config_file = tmp_path / 'config.json'
    config_file.write_text(json.dumps(config))
    no_links = pub.no_links
    def map_path(path):
        value = str(path)
        if value.startswith('/opt/xiquan/xiquan/deploy/cloud'):
            return no_links(cloud / value.removeprefix('/opt/xiquan/xiquan/deploy/cloud').lstrip('/'))
        if value == '/opt/xiquan-backups':
            return backups
        return no_links(path)
    monkeypatch.setattr(pub, 'no_links', map_path)
    class Response:
        status = 200
        headers = {'Content-Length': str(incoming.stat().st_size)}
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr('urllib.request.urlopen', lambda request, timeout: Response())
    pub.publish(config_file, incoming)
    for name, content in retained.items():
        assert (cloud / name).read_bytes() == content
    published = json.loads(policy.read_text(encoding='utf-8'))
    assert published['desktop'] == old['desktop'] and published['web'] == old['web']
    assert published['android']['sha256'] == config['sha256']
    assert (cloud / 'mobile/downloads/xiquan-mobile-ordering-1.2.6.apk').read_bytes() == incoming.read_bytes()
