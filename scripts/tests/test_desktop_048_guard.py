"""The guard rejects every retained-data change outside the 0.4.8 allowance."""
import copy
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))
sys.path.insert(0, str(ROOT / 'server'))


def module():
    assert (ROOT / 'deploy/cloud/scripts/desktop_048_guard.py').is_file(), '0.4.8 retained-data guard missing'
    return importlib.import_module('desktop_048_guard')


def fixture():
    before = {'tables': {name: {'rows': 3, 'sha256': 'same', 'columns': {
        'id': {'type': 'VARCHAR', 'nullable': False, 'default': None}}} for name in
        ('members', 'stock_items', 'catalog_items', 'stock_costs', 'audit_logs',
         'schema_upgrade_markers', 'alembic_version', 'business_state')},
        'roles': 'same', 'owners': {'members': 'owner'}, 'audit_valid': True,
        'schema': '20261007_insights_cost', 'unit_cost_nonnull': None, 'business_revision': 41,
        'catalog_flags': {'towel': {'kind': 'product', 'stock_tracked': True},
                          'supplies': {'kind': 'product', 'stock_tracked': False},
                          'existing-service': {'kind': 'service', 'stock_tracked': True}}}
    after = copy.deepcopy(before)
    after['schema'] = '20261007_ordering_cost'
    after['tables']['stock_items']['columns']['unit_cost'] = {
        'type': 'NUMERIC(12, 2)', 'nullable': True, 'default': None}
    after['unit_cost_nonnull'] = 0
    after['business_revision'] = 43
    for id_ in ('towel', 'supplies'):
        after['catalog_flags'][id_] = {'kind': 'service', 'stock_tracked': False}
    return before, after


def test_accepts_only_nullable_empty_cost_and_known_product_conversion():
    before, after = fixture()
    module().compare(before, after)


@pytest.mark.parametrize('table', ('members', 'stock_items', 'catalog_items', 'stock_costs',
                                 'audit_logs', 'schema_upgrade_markers', 'alembic_version', 'business_state'))
def test_rejects_changed_history_alerts_prices_quantities_and_rows(table):
    guard = module()
    before, after = fixture()
    after['tables'][table]['sha256'] = 'changed retained field'
    with pytest.raises(guard.GuardError, match='Retained'):
        guard.compare(before, after)


@pytest.mark.parametrize('column', (
    {'type': 'NUMERIC(12, 2)', 'nullable': False, 'default': None},
    {'type': 'NUMERIC(12, 2)', 'nullable': True, 'default': '0'},
    {'type': 'NUMERIC(10, 2)', 'nullable': True, 'default': None},
))
def test_rejects_cost_zeroing_and_wrong_cost_schema(column):
    guard = module()
    before, after = fixture()
    after['tables']['stock_items']['columns']['unit_cost'] = column
    with pytest.raises(guard.GuardError):
        guard.compare(before, after)


def test_rejects_seeded_costs_missing_rows_new_tables_and_unlisted_catalog_changes():
    guard = module()
    before, after = fixture()
    changes = [lambda row: row.update(unit_cost_nonnull=1),
               lambda row: row['tables']['stock_items'].update(rows=2),
               lambda row: row['tables'].update(unexpected={'rows': 0}),
               lambda row: row['catalog_flags']['existing-service'].update(stock_tracked=False),
               lambda row: row['catalog_flags']['towel'].update(stock_tracked=True),
               lambda row: row['catalog_flags'].update(unlisted={'kind': 'service', 'stock_tracked': False}),
               lambda row: row.update(roles='changed'),
               lambda row: row['owners'].update(members='changed'),
               lambda row: row.update(audit_valid=False)]
    for change in changes:
        changed = copy.deepcopy(after)
        change(changed)
        with pytest.raises(guard.GuardError):
            guard.compare(before, changed)


@pytest.mark.parametrize('revision', (41, 42, 44))
def test_requires_exact_catalog_trigger_revision_increment(revision):
    guard = module()
    before, after = fixture()
    after['business_revision'] = revision
    with pytest.raises(guard.GuardError, match='revision'):
        guard.compare(before, after)


def test_rejects_unexpected_existing_stock_column_change():
    guard = module()
    before, after = fixture()
    after['tables']['stock_items']['columns']['id']['nullable'] = True
    with pytest.raises(guard.GuardError, match='Retained'):
        guard.compare(before, after)
