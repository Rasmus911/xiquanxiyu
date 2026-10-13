"""Preservation gates: an additive release cannot rewrite any existing account."""
import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'deploy/cloud/scripts'), str(ROOT / 'server')]


def snapshots():
    names = ('members', 'employees', 'member_passes', 'stock_items', 'audit_logs',
             'payments', 'visits', 'alembic_version', 'business_state')
    before = dict(schema_revision='20261011_service_receipts', roles='unchanged',
                  audit_valid=True, old_row_hashes={n: {'rows': 2, 'sha256': n} for n in names},
                  new_row_counts={}, columns={n: {'id': dict(type='VARCHAR', nullable=False, default=None)} for n in names},
                  owners={n: 'owner' for n in names}, grants={n: ['unchanged'] for n in names},
                  foreign_keys={n: [] for n in names}, indexes={n: [] for n in names})
    before['columns']['members']['phone'] = dict(type='VARCHAR(20)', nullable=False, default=None)
    after = copy.deepcopy(before)
    after['schema_revision'] = '20261012_physical_membership'
    after['columns']['members']['phone']['nullable'] = True
    after['columns']['members']['holder_surname'] = dict(type='VARCHAR(40)', nullable=True, default=None)
    for name in ('member_card_bindings', 'settlement_pass_redemptions'):
        after['new_row_counts'][name] = 0
        after['owners'][name] = 'owner'
    after['runtime_roles'] = {'verified': True}
    after['surname_nonnull'] = 0
    return before, after


def test_migration_never_allows_member_balance_drift():
    from desktop_051_guard import compare_migration
    before, after = snapshots()
    after['old_row_hashes']['members']['sha256'] = 'changed-balance'
    with pytest.raises(RuntimeError, match='Retained data'):
        compare_migration(before, after)


def test_only_exact_empty_addition_and_nullable_phone_extension_are_accepted():
    from desktop_051_guard import compare_migration
    compare_migration(*snapshots())


@pytest.mark.parametrize('table', ['employees', 'member_passes', 'stock_items', 'audit_logs', 'payments', 'visits'])
def test_every_existing_row_is_preserved_without_employee_deletion_exceptions(table):
    from desktop_051_guard import compare_migration
    before, after = snapshots()
    after['old_row_hashes'][table]['rows'] -= 1
    with pytest.raises(RuntimeError, match='Retained data'):
        compare_migration(before, after)


@pytest.mark.parametrize('mutation', ['extra-table', 'missing-table', 'fixture', 'phone-type', 'surname-default',
                                    'role', 'grant', 'owner', 'foreign-key', 'index', 'audit', 'privileges', 'surname-data'])
def test_unreviewed_schema_or_authority_change_is_rejected(mutation):
    from desktop_051_guard import compare_migration
    before, after = snapshots()
    if mutation == 'extra-table': after['new_row_counts']['unexpected'] = 0
    elif mutation == 'missing-table': after['old_row_hashes'].pop('employees')
    elif mutation == 'fixture': after['new_row_counts']['member_card_bindings'] = 1
    elif mutation == 'phone-type': after['columns']['members']['phone']['type'] = 'TEXT'
    elif mutation == 'surname-default': after['columns']['members']['holder_surname']['default'] = "'x'"
    elif mutation == 'role': after['roles'] = 'altered-password'
    elif mutation == 'grant': after['grants']['members'] = ['excess']
    elif mutation == 'owner': after['owners']['members'] = 'other'
    elif mutation == 'foreign-key': after['foreign_keys']['members'] = ['changed']
    elif mutation == 'index': after['indexes']['members'] = ['changed']
    elif mutation == 'audit': after['audit_valid'] = False
    elif mutation == 'surname-data': after['surname_nonnull'] = 1
    else: after['runtime_roles'] = {'verified': False}
    with pytest.raises(RuntimeError): compare_migration(before, after)


def test_projection_excludes_only_new_surname_and_revision_value():
    from desktop_051_guard import row_projection
    assert row_projection('members') == "to_jsonb(t) - 'holder_surname'"
    assert row_projection('employees') == 'to_jsonb(t)'
    assert row_projection('alembic_version') == "to_jsonb(t) - 'version_num'"


def test_rehearsal_refuses_real_database_endpoint():
    from desktop_051_guard import require_isolated
    from sqlalchemy.engine import make_url
    with pytest.raises(RuntimeError, match='isolated'):
        require_isolated(make_url('postgresql://postgres/production'))


def test_table_owner_rows_are_materialized_from_real_sqlalchemy_result():
    from desktop_051_guard import table_owners
    from sqlalchemy import create_engine
    with create_engine('sqlite://').begin() as connection:
        connection.connection.driver_connection.create_function('pg_get_userbyid', 1, lambda _: 'owner')
        connection.exec_driver_sql('CREATE TABLE pg_class(relname,relowner,relnamespace,relkind)')
        connection.exec_driver_sql('CREATE TABLE pg_namespace(oid,nspname)')
        connection.exec_driver_sql("INSERT INTO pg_namespace VALUES (1,'public'),(2,'private')")
        connection.exec_driver_sql("INSERT INTO pg_class VALUES ('members',5,1,'r'),('not-public',5,2,'r')")
        assert table_owners(connection) == {'members': 'owner'}
