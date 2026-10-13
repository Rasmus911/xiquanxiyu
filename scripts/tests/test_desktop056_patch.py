import importlib
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy/cloud/scripts'))

def test_api_format_patch_accepts_only_reviewed_original_and_target():
    api=importlib.import_module('desktop056_format_patch')
    incoming=(Path(__file__).resolve().parents[2]/'server/app/inventory_xlsx.py').read_bytes()
    assert api.normalized_hash(incoming)==api.PATCH_SHA256
    api.verify_patch(incoming,incoming,hashlib.sha256(incoming).hexdigest())
    with pytest.raises(ValueError):api.verify_patch(b'unknown source',incoming,hashlib.sha256(incoming).hexdigest())
    with pytest.raises(ValueError):api.verify_patch(incoming,incoming+b'\n# unreviewed',hashlib.sha256(incoming+b'\n# unreviewed').hexdigest())

def test_static_publish_preserves_old_assets_and_desktop_android_policies(tmp_path,monkeypatch):
    api=importlib.import_module('static056_publication');original_safe=api.safe
    def fixture_safe(path):
        path=str(path)
        if path.startswith('/opt/'):path=str(tmp_path/path.lstrip('/'))
        return original_safe(path)
    monkeypatch.setattr(api,'safe',fixture_safe)
    cloud=tmp_path/'opt/xiquan/xiquan/deploy/cloud';(cloud/'web/assets').mkdir(parents=True);(cloud/'releases').mkdir()
    (tmp_path/'opt/xiquan-backups').mkdir()
    policy={'schemaVersion':1,'desktop':{'latestVersion':'0.5.5'},'android':{'latestVersionCode':19},'web':{'buildId':'old'}}
    (cloud/'releases/client-policy.json').write_text(json.dumps(policy));(cloud/'web/assets/old.js').write_text('old')
    archive=tmp_path/'web.zip'
    with ZipFile(archive,'w') as zipped:
        zipped.writestr('index.html','<script src="./assets/new.js"></script>');zipped.writestr('assets/new.js','new');zipped.writestr('version.json','{}')
    api.publish(archive,api.digest(archive),'a'*40)
    after=json.loads((cloud/'releases/client-policy.json').read_text(encoding='utf-8'))
    assert after['desktop']==policy['desktop'] and after['android']==policy['android']
    assert after['web']['buildId']=='a'*40
    assert (cloud/'web/assets/old.js').read_text()=='old'
    assert (cloud/'web/assets/new.js').read_text()=='new'

def test_android_1213_preserves_other_channels_and_refuses_same_code_changed_bytes():
    api=importlib.import_module('android_1213_publication')
    before={'schemaVersion':1,'desktop':{'latestVersion':'0.5.6'},'web':{'buildId':'correct'},'android':{'latestVersion':'1.2.12','latestVersionCode':19,'minimumVersionCode':9}}
    config={'version':'1.2.13','versionCode':20,'minimumVersionCode':9,'androidApkUrl':'/mobile/downloads/xiquan-mobile-ordering-1.2.13.apk','sha256':'b'*64,'releaseNotes':'图标\n库存'}
    after=api.merge_policy(before,config)
    assert after['desktop']==before['desktop'] and after['web']==before['web']
    with pytest.raises(ValueError):api.merge_policy(after,{**config,'sha256':'c'*64})
