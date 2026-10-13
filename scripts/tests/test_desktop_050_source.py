import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'deploy/cloud/scripts'),str(ROOT/'server')]

def source(tmp_path):
    deploy=importlib.import_module('desktop_050_deploy');folder=tmp_path/'xiquan'
    files={'client/package.json':b'{"version":"0.5.0"}', 'mobile/version.json':b'{"version":"1.2.9"}',
        'server/app/employee_identity.py':b'# reviewed\n', 'server/app/receipt_cleanup_worker.py':b'# reviewed\n',
        'server/migrations/versions/20261011_employee_identity.py':b'# reviewed\n',
        'server/migrations/versions/20261011_service_receipts.py':b'# reviewed\n'}
    for name in deploy.TOOLS:files['deploy/cloud/scripts/'+name]=(ROOT/'deploy/cloud/scripts'/name).read_bytes()
    records=[]
    for name,data in files.items():
        file=folder/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
        records.append(dict(file=name,size=len(data),sha256=hashlib.sha256(data).hexdigest()))
    (folder/'source-manifest.json').write_text(json.dumps(dict(source_commit='a'*40,files=records)))
    return deploy,folder

def test_frozen_source_versions_and_transport_bytes(tmp_path):
    deploy,folder=source(tmp_path);assert deploy.verify_source(folder)['source_commit']=='a'*40
    (folder/'server/app/employee_identity.py').write_bytes(b'altered')
    with pytest.raises(deploy.DeploymentError):deploy.verify_source(folder)

def test_actual_source_version_and_current_tools_are_packaged():
    assert json.loads((ROOT/'client/package.json').read_text(encoding='utf-8'))['version']=='0.5.0'
    names=['scripts/build-desktop-050.ps1','scripts/sign-desktop-050.ps1','scripts/invoke-desktop-050.ps1',
        'scripts/lib/desktop-050.cjs','deploy/cloud/scripts/desktop_050_guard.py','deploy/cloud/scripts/desktop_050_deploy.py']
    result=subprocess.run(['node','-e','const s=require("./scripts/lib/source-security.cjs");console.log(JSON.stringify(process.argv.slice(1).map(x=>s.allowed(x))))',*names],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0 and json.loads(result.stdout)==[True]*len(names)

def test_publication_requires_exact_cloud_completed_not_only_typed_confirmation():
    script=(ROOT/'scripts/desktop-050-publish-entry.ps1').read_text(encoding='utf-8-sig')
    for marker in ('completed.json','SourceCommit','SourceSha256','20261011_service_receipts','receipt_cleanup'):
        assert marker in script
    assert r'溪泉洗浴系统\private\溪泉发布密钥' in script
