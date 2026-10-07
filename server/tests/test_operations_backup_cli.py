"""Breaks caught: alias restores, stale snapshots and premature verified receipts."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.extensions import db


def snapshot(*, server='source-cluster', database='bathhouse'):
    return {
        'server': {'system_identifier': server, 'pg_major': 17, 'database': database},
        'identity': {'db_name': database, 'alembic_revision': '20261004_catalog_packages',
                     'business_period_id': 'fixture-period', 'business_revision': 479,
                     'audit_checkpoint': {'chain_index': 285, 'current_hash': 'a' * 64}},
        'tables': {'employees': {'rows': 6, 'sha256': 'b' * 64},
                   'members': {'rows': 2, 'sha256': 'c' * 64},
                   'catalog_items': {'rows': 8, 'sha256': 'd' * 64},
                   'audit_logs': {'rows': 285, 'sha256': 'e' * 64}},
        'totals': {'member_balance': '109.00', 'stock_quantity': '17.000'},
        'audit_valid': True,
    }


def pending_candidate():
    return {'schema': 1, **snapshot()['identity'], 'dump_path': '/private/database.backup',
            'dump_sha256': 'f' * 64, 'dump_size': 1234, 'checks': snapshot(),
            'restore': {'status': 'pending'}}


def test_verified_receipt_requires_matching_rows_and_actual_different_server():
    from app.operations_backup import compose_verified_receipt
    restored = snapshot(server='isolated-cluster', database='restore_test')
    result = compose_verified_receipt(pending_candidate(), snapshot(), restored)
    assert result['db_name'] == 'bathhouse'
    assert result['restore']['status'] == 'verified'
    assert result['restore']['source_server_id'] == 'source-cluster'
    assert result['restore']['restored_server_id'] == 'isolated-cluster'
    assert result['restore']['pg_major'] == 17
    assert len(result['restore']['checks_sha256']) == 64


def test_different_database_name_on_same_server_is_not_isolated():
    from app.operations_backup import BackupReceiptError, compose_verified_receipt
    with pytest.raises(BackupReceiptError, match='isolated'):
        compose_verified_receipt(pending_candidate(), snapshot(), snapshot(database='other'))


def test_same_database_name_on_actual_different_server_is_allowed():
    from app.operations_backup import compose_verified_receipt
    assert compose_verified_receipt(pending_candidate(), snapshot(),
        snapshot(server='isolated-cluster'))['restore']['status'] == 'verified'


@pytest.mark.parametrize('breakage', ['balance-row', 'stock-row', 'missing-table', 'row-count',
                                    'audit-invalid', 'audit-tail', 'revision', 'period', 'pg16'])
def test_mismatched_restores_never_produce_verified_receipt(breakage):
    from app.operations_backup import BackupReceiptError, compose_verified_receipt
    restored = snapshot(server='isolated-cluster', database='restore_test')
    if breakage == 'balance-row': restored['tables']['members']['sha256'] = '0' * 64
    elif breakage == 'stock-row': restored['tables']['catalog_items']['sha256'] = '0' * 64
    elif breakage == 'missing-table': del restored['tables']['employees']
    elif breakage == 'row-count': restored['tables']['audit_logs']['rows'] -= 1
    elif breakage == 'audit-invalid': restored['audit_valid'] = False
    elif breakage == 'audit-tail': restored['identity']['audit_checkpoint']['chain_index'] -= 1
    elif breakage == 'revision': restored['identity']['alembic_revision'] = 'older'
    elif breakage == 'period': restored['identity']['business_period_id'] = 'other'
    elif breakage == 'pg16': restored['server']['pg_major'] = 16
    with pytest.raises(BackupReceiptError):
        compose_verified_receipt(pending_candidate(), snapshot(), restored)


@pytest.mark.parametrize('breakage', ['business-revision', 'audit', 'rows', 'server'])
def test_source_changed_after_dump_stops_verification(breakage):
    from app.operations_backup import BackupReceiptError, compose_verified_receipt
    live = snapshot()
    if breakage == 'business-revision': live['identity']['business_revision'] += 1
    elif breakage == 'audit': live['identity']['audit_checkpoint']['current_hash'] = '0' * 64
    elif breakage == 'rows': live['tables']['members']['rows'] += 1
    elif breakage == 'server': live['server']['system_identifier'] = 'different-source'
    with pytest.raises(BackupReceiptError, match='changed'):
        compose_verified_receipt(pending_candidate(), live, snapshot(server='isolated-cluster'))


def test_list_only_or_reused_receipt_cannot_be_finalized():
    from app.operations_backup import BackupReceiptError, compose_verified_receipt
    for status in ('list-only', 'verified'):
        candidate = pending_candidate()
        candidate['restore']['status'] = status
        with pytest.raises(BackupReceiptError):
            compose_verified_receipt(candidate, snapshot(), snapshot(server='isolated-cluster'))


def test_private_json_writes_are_exclusive_and_do_not_overwrite(app, tmp_path):
    from app.operations_backup import BackupReceiptError, write_private_json
    from app.reset_backup import private_directory
    app.config['RESET_PRIVATE_DIR'] = str(tmp_path / 'private')
    root = private_directory('operations')
    target = root / 'candidate.json'
    write_private_json(target, {'restore': {'status': 'pending'}})
    with pytest.raises(BackupReceiptError):
        write_private_json(target, {'restore': {'status': 'verified'}})
    assert json.loads(target.read_text())['restore']['status'] == 'pending'


def test_backup_cli_is_registered_and_refuses_nonmaintenance_sqlite(app, tmp_path):
    runner = app.test_cli_runner()
    assert 'operations-backup' in runner.invoke(args=['--help']).output
    result = runner.invoke(args=['operations-backup', 'create', '--output', str(tmp_path / 'not-created')])
    assert result.exit_code != 0
    assert 'maintenance' in result.output.lower()
    assert not (tmp_path / 'not-created').exists()


def test_restore_url_errors_do_not_disclose_private_credentials(app, monkeypatch, tmp_path):
    app.config['MAINTENANCE_PROCESS'] = True
    secret = 'test-only-hidden-database-password'
    monkeypatch.setenv('XIQUAN_RESTORE_DATABASE_URL', f'postgresql+psycopg://fixture:{secret}@127.0.0.1/fixture')
    result = app.test_cli_runner().invoke(args=['operations-backup', 'verify-restored',
        '--database-url-env', 'XIQUAN_RESTORE_DATABASE_URL', '--receipt', str(tmp_path / 'absent.json')])
    assert result.exit_code != 0
    assert secret not in result.output


def test_dump_uses_exported_snapshot_and_never_puts_password_in_argv(app, monkeypatch, tmp_path):
    from app.operations_backup import run_snapshot_dump
    app.config.update(RESET_BACKUP_DATABASE_URL='postgresql+psycopg://backup:test-only-hidden@postgres/bathhouse',
                      PG_DUMP_PATH='pg_dump', PG_RESTORE_PATH='pg_restore')
    from sqlalchemy.engine import make_url
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        class Result:
            stdout = 'pg_dump (PostgreSQL) 17.11'
        return Result()
    monkeypatch.setattr('app.operations_backup.subprocess.run', run)
    run_snapshot_dump(make_url('postgresql+psycopg://owner:fixture-only@postgres/bathhouse'),
                      '00000005-000000E4-1', tmp_path / 'new.backup')
    dump_calls = [(argv, kw) for argv, kw in calls if '--format=custom' in argv]
    assert len(dump_calls) == 1
    argv, options = dump_calls[0]
    assert '--snapshot=00000005-000000E4-1' in argv
    assert 'test-only-hidden' not in ' '.join(argv)
    assert options['env']['PGPASSWORD'] == 'test-only-hidden'
    assert options['env']['PGOPTIONS'] == '-c default_transaction_read_only=on'
