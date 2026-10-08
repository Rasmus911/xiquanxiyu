import copy
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))


def publisher():
    assert (ROOT / 'deploy/cloud/scripts/android_127_publication.py').exists(), 'Android publication missing'
    return importlib.import_module('android_127_publication')


def inputs():
    return ({'schemaVersion': 1, 'desktop': {'retained': True}, 'web': {'retained': True},
             'android': {'latestVersion': '1.2.6', 'latestVersionCode': 13, 'minimumVersionCode': 9}},
            {'version': '1.2.7', 'versionCode': 14, 'minimumVersionCode': 9,
             'androidApkUrl': '/mobile/downloads/xiquan-mobile-ordering-1.2.7.apk',
             'sha256': 'a' * 64, 'releaseNotes': '新增 账号注册功能'})


def test_merge_retains_other_platforms_and_exact_android_contract():
    p = publisher()
    previous, config = inputs()
    unchanged = copy.deepcopy(previous)
    result = p.merge_policy(previous, config)
    assert previous == unchanged
    assert result['desktop'] == previous['desktop'] and result['web'] == previous['web']
    assert result['android']['latestVersionCode'] == 14
    assert result['android']['minimumVersionCode'] == 9


@pytest.mark.parametrize('mutation', ['version', 'hash', 'newer', 'same_code', 'minimum'])
def test_rejects_unsafe_android_publication(mutation):
    p = publisher()
    previous, config = inputs()
    if mutation == 'version': config['versionCode'] = 13
    if mutation == 'hash': config['sha256'] = 'invalid'
    if mutation == 'newer': previous['android']['latestVersionCode'] = 15
    if mutation == 'same_code': previous['android'].update(latestVersionCode=14, sha256='b' * 64)
    if mutation == 'minimum': previous['android']['minimumVersionCode'] = 10
    with pytest.raises(ValueError): p.merge_policy(previous, config)
