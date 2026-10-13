import importlib
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy/cloud/scripts'))

def test_android_policy_preserves_desktop_and_rejects_code_reuse():
    api=importlib.import_module('android_1212_publication')
    previous={'schemaVersion':1,'desktop':{'latestVersion':'0.5.5'},'web':{'buildId':'exact'},'android':{'latestVersion':'1.2.11','latestVersionCode':18,'minimumVersionCode':9}}
    config={'version':'1.2.12','versionCode':19,'minimumVersionCode':9,'androidApkUrl':'/mobile/downloads/xiquan-mobile-ordering-1.2.12.apk','sha256':'a'*64,'releaseNotes':'取消下单“选择耗材”的步骤\n可以通过导入外部Excel来整理库存'}
    result=api.merge_policy(previous,config)
    assert result['desktop']==previous['desktop'] and result['web']==previous['web']
    assert result['android']['latestVersionCode']==19 and result['android']['releaseNotes']==['取消下单“选择耗材”的步骤','可以通过导入外部Excel来整理库存']
    with pytest.raises(ValueError):api.merge_policy(result,{**config,'sha256':'b'*64})
    with pytest.raises(ValueError):api.merge_policy(result,{**config,'versionCode':18})
