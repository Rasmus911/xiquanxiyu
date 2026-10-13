import importlib
import copy
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy/cloud/scripts'))

def test_guard_includes_only_the_new_nullable_cost_columns_in_the_allowed_projection():
    guard=importlib.import_module('desktop_055_guard')
    assert guard.row_projection('members')=='to_jsonb(t)'
    assert guard.row_projection('stock_items')=="to_jsonb(t) - 'reference_cost' - 'cost_basis'"
    with pytest.raises(RuntimeError):guard.row_projection('stock_items;DROP TABLE members')

def test_upload_config_is_idempotent_and_preserves_every_existing_location():
    driver=importlib.import_module('desktop_055_deploy')
    original='server {\n    client_max_body_size 2m;\n    location / {\n        proxy_pass http://api:5000;\n    }\n}\n'
    configured=driver.excel_upload_configuration(original)
    assert configured.count('client_max_body_size 15m;')==1
    assert original[original.index('    location / {'):] in configured
    assert driver.excel_upload_configuration(configured)==configured
    with pytest.raises(driver.DeploymentError):driver.excel_upload_configuration('server {}')

def test_checkpoint_does_not_replay_unknown_already_migrated_schema(tmp_path):
    driver=importlib.import_module('desktop_055_deploy')
    checkpoint=driver.Checkpoints(tmp_path,{'job':'owner'})
    with pytest.raises(driver.DeploymentError,match='do not replay DDL'):
        checkpoint.classify('20261013_manual_inventory_excel',True,'owner')

def migration_pair():
    guard=importlib.import_module('desktop_055_guard')
    old=dict(schema_revision=guard.OLD,new_row_counts={},old_row_hashes={'members':{'rows':1,'sha256':'member-hash'},'stock_items':{'rows':1,'sha256':'stock-hash'}},
        columns={'members':{},'stock_items':{}},roles='same-role-hash',audit_valid=True,owners={'members':'owner','stock_items':'owner'},
        grants={'members':[],'stock_items':[]},foreign_keys={'members':[],'stock_items':[]},indexes={'members':[],'stock_items':[]})
    new=copy.deepcopy(old);new.update(schema_revision=guard.HEAD,new_row_counts={name:0 for name in guard.NEW},new_cost_populated=0,runtime_roles={'verified':True})
    new['columns']['stock_items']={'reference_cost':{'type':'NUMERIC(12, 2)','nullable':True,'default':None},'cost_basis':{'type':'VARCHAR(7)','nullable':True,'default':None}}
    new['owners'].update({name:'owner' for name in guard.NEW})
    return guard,old,new

def test_additive_comparison_accepts_only_empty_new_tables_and_null_costs():
    guard,old,new=migration_pair();guard.compare_migration(old,new)
    for change in ('rows','guessed-cost','wrong-owner','old-stock-change'):
        bad=copy.deepcopy(new)
        if change=='rows':bad['new_row_counts']['stock_import_pending']=1
        elif change=='guessed-cost':bad['new_cost_populated']=1
        elif change=='wrong-owner':bad['owners']['stock_import_pending']='runtime'
        else:bad['old_row_hashes']['stock_items']['sha256']='changed'
        with pytest.raises(RuntimeError):guard.compare_migration(old,bad)

def test_nginx_route_receipt_does_not_allow_changes_to_any_other_release_file(tmp_path,monkeypatch):
    driver=importlib.import_module('desktop_055_deploy')
    original={'sha256':'original','size':10,'inode':1,'device':1}
    after={'sha256':'reviewed','size':11,'inode':2,'device':1}
    protected={'nginx/active.conf':original,'mobile/download-config.json':{'sha256':'apk','size':50,'inode':3,'device':1}}
    actual={**protected,'nginx/active.conf':after}
    monkeypatch.setattr(driver,'protected_files',lambda _:actual)
    (tmp_path/'nginx-excel-switch.json').write_text(json.dumps({'original':original,'after':{'sha256':'reviewed','size':11}}))
    deployment=driver.Desktop055.__new__(driver.Desktop055);deployment.job=tmp_path;deployment.report={'protected':protected}
    deployment.protected()
    actual['mobile/download-config.json']={**protected['mobile/download-config.json'],'sha256':'unauthorized'}
    with pytest.raises(driver.DeploymentError):deployment.protected()
