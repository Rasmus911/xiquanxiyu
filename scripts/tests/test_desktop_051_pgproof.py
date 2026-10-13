import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'deploy/cloud/scripts'), str(ROOT / 'server')]


def test_parallel_proof_requires_two_overlapping_workers_and_returns_both_results():
    from desktop_051_pgproof import parallel
    gate = threading.Barrier(2)
    def first():
        gate.wait(timeout=2)
        return 'first'
    def second():
        gate.wait(timeout=2)
        return 'second'
    assert parallel(first, second) == ['first', 'second']


def test_parallel_proof_propagates_worker_failure():
    from desktop_051_pgproof import parallel
    def failure(): raise RuntimeError('isolated failure')
    with pytest.raises(RuntimeError, match='isolated failure'): parallel(failure, lambda: 'other')


def test_proof_rejects_nonisolated_urls_before_fixture_access():
    from desktop_051_pgproof import validate_endpoints
    from sqlalchemy.engine import make_url
    with pytest.raises(RuntimeError, match='isolated'):
        validate_endpoints([make_url('postgresql+psycopg://owner@postgres/prod')])


def test_proof_rejects_different_restore_databases():
    from desktop_051_pgproof import validate_endpoints
    from sqlalchemy.engine import make_url
    with pytest.raises(RuntimeError):
        validate_endpoints([make_url('postgresql+psycopg://a@xiquan-operations-restore-a/operations_restore'),
                            make_url('postgresql+psycopg://b@xiquan-operations-restore-b/operations_restore')])


@pytest.mark.parametrize('wrong_code', [None, '25006', 'P0001'])
def test_backup_proof_separates_default_readonly_from_clone_readwrite_acl(wrong_code):
    # Removing SET TRANSACTION READ WRITE would leave the second UPDATE at 25006.
    from desktop_051_pgproof import prove_backup_write_denials
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    calls = []
    class Connection:
        readonly = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def exec_driver_sql(self, sql):
            calls.append(sql)
            if sql == 'SET TRANSACTION READ WRITE': self.readonly = False
            value = 'xiquan_backup' if sql == 'SELECT session_user' else 'on'
            return type('Result', (), {'scalar_one': lambda _: value})()
        def execute(self, sql, values):
            calls.append(str(sql))
            error = Exception('private test denial')
            error.sqlstate = '25006' if self.readonly else (wrong_code or '42501')
            raise DBAPIError(str(sql), values, error)
        def rollback(self): pass
    class Engine:
        url = make_url('postgresql+psycopg://xiquan_backup@xiquan-operations-restore-a/operations_restore')
        def connect(self): return Connection()
    if wrong_code:
        with pytest.raises(RuntimeError, match='Wrong PostgreSQL denial'): prove_backup_write_denials(Engine())
    else:
        assert prove_backup_write_denials(Engine()) == {'default_readonly': '25006', 'readwrite_acl': '42501'}
    assert 'SHOW default_transaction_read_only' in calls
    assert 'SHOW transaction_read_only' in calls
    assert calls.count('SET TRANSACTION READ WRITE') == 1


def test_backup_readwrite_proof_refuses_nonclone_before_connect():
    from desktop_051_pgproof import prove_backup_write_denials
    from sqlalchemy.engine import make_url
    engine = type('Engine', (), {'url': make_url('postgresql+psycopg://xiquan_backup@postgres/production')})()
    with pytest.raises(RuntimeError, match='isolated'): prove_backup_write_denials(engine)
