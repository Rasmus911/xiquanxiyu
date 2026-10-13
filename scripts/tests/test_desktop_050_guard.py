import copy
import importlib
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'deploy/cloud/scripts'),str(ROOT/'server')]

def guard(): return importlib.import_module('desktop_050_guard')
def snapshots():
    names=('members','member_passes','stock_items','payments','audit_logs','order_items','employees','print_jobs','alembic_version')
    before=dict(schema='20261008_registration_token',roles='same',audit_valid=True,
        tables={name:dict(rows=2,sha256='same') for name in names},
        columns={name:{'id':'VARCHAR'} for name in names},owners={name:'owner' for name in names},
        grants={name:['same'] for name in names},foreign_keys={},
        retained_employees=dict(rows=1,sha256='retained-employee'),identity_expected=dict(rows=2,sha256='identities'))
    after=copy.deepcopy(before);after['schema']='20261011_service_receipts'
    after['tables']['employees']=copy.deepcopy(before['retained_employees'])
    after['tables']['employee_identities']=copy.deepcopy(before['identity_expected'])
    for name in ('service_print_jobs','service_print_attempts','settlement_print_attempts'):
        after['tables'][name]=dict(rows=0,sha256='empty')
    for name in set(after['tables'])-set(before['tables']): after['owners'][name]='owner'
    after['receipt_privileges_valid']=True
    return before,after

def test_exact_addition_and_reviewed_soft_account_cleanup_are_accepted(): guard().compare(*snapshots())
@pytest.mark.parametrize('name',['members','member_passes','stock_items','payments','audit_logs','order_items','employees','employee_identities'])
def test_any_unreviewed_retained_row_change_is_rejected(name):
    before,after=snapshots();after['tables'][name]['sha256']='corrupt'
    with pytest.raises(Exception,match='changed|identity|employee'):guard().compare(before,after)
def test_grant_or_schema_mutation_cannot_be_ignored():
    for key in ['roles','schema','receipt_privileges_valid']:
        before,after=snapshots();after[key]=False
        with pytest.raises(Exception):guard().compare(before,after)
def test_receipt_probe_never_accepts_a_production_endpoint():
    from sqlalchemy.engine import make_url
    with pytest.raises(Exception,match='isolated'):guard().require_isolated(make_url('postgresql://postgres/production'))
