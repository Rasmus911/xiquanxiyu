import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

module_path=Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts/android_125_publication.py'
spec=importlib.util.spec_from_file_location('android_125_publication',module_path)
pub=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


def test_android_policy_merge_preserves_desktop_and_web_and_rejects_code_rollback():
    old={'schemaVersion':1,'desktop':{'latestVersion':'0.4.7','signature':'kept'},
         'web':{'buildId':'kept'},'android':{'latestVersion':'1.2.3','latestVersionCode':10,'minimumVersionCode':9}}
    candidate={'version':'1.2.5','versionCode':12,'minimumVersionCode':9,
        'androidApkUrl':'/mobile/downloads/xiquan-mobile-ordering-1.2.5.apk','sha256':'a'*64,'releaseNotes':'手机同步'}
    updated=pub.merge_policy(old,candidate)
    assert updated['desktop'] == old['desktop'] and updated['web'] == old['web']
    assert updated['android']['latestVersionCode'] == 12
    assert old['android']['latestVersionCode'] == 10
    newer=json.loads(json.dumps(old)); newer['android']['latestVersionCode']=13
    with pytest.raises(ValueError): pub.merge_policy(newer,candidate)
