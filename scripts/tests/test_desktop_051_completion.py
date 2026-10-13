import copy
import importlib
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'deploy/cloud/scripts'))
module=importlib.import_module('desktop_051_completion')

def fixtures():
    receipt=dict(phase='completed',source_commit='a'*40,source_sha256='b'*64,target_schema='20261012_physical_membership',image_id='sha256:'+'c'*64,origin={'hashes':{'origin:health':'d'*64}})
    container={'Image':receipt['image_id'],'State':{'Running':True,'Health':{'Status':'healthy'}}}
    database=dict(schema=receipt['target_schema'],maintenance=False,owner=None)
    return receipt,container,database

def test_exact_completed_and_live_identity():
    r,c,d=fixtures()
    assert module.validate(r,'a'*40,'b'*64,c,c,d)['completed'] is True

@pytest.mark.parametrize('patch',[{'phase':'ready'},{'target_schema':'20261011_service_receipts'},{'source_commit':'e'*40},{'source_sha256':'f'*64},{'origin':{}}])
def test_old_or_incomplete_evidence_rejected(patch):
    r,c,d=fixtures();r.update(patch)
    with pytest.raises(RuntimeError):module.validate(r,'a'*40,'b'*64,c,c,d)

def test_unhealthy_worker_different_image_and_maintenance_rejected():
    r,c,d=fixtures()
    wrong=copy.deepcopy(c);wrong['State']['Health']['Status']='unhealthy'
    with pytest.raises(RuntimeError):module.validate(r,'a'*40,'b'*64,c,wrong,d)
    wrong=copy.deepcopy(c);wrong['Image']='sha256:'+'e'*64
    with pytest.raises(RuntimeError):module.validate(r,'a'*40,'b'*64,wrong,c,d)
    for patch in ({'maintenance':True},{'owner':'owner'},{'schema':'old'}):
        with pytest.raises(RuntimeError):module.validate(r,'a'*40,'b'*64,c,c,{**d,**patch})
