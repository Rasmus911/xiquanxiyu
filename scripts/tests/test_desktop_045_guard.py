import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('desktop_guard', SCRIPTS / 'desktop_045_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def fixture_snapshot():
    return {'tables': {name: {'columns': {'id': 'VARCHAR'}, 'rows': 2, 'sha256': 'fixture-hash'}
                       for name in ('members', 'catalog_items', 'stock_items', 'audit_logs', 'alembic_version')},
            'owners': {name: 'fixture-owner' for name in ('members', 'catalog_items', 'stock_items', 'audit_logs', 'alembic_version')},
            'roles': 'fixture-role-hash', 'audit_valid': True}


def test_migration_accepts_only_reviewed_additions_not_money_inventory_accounts_or_history_changes():
    import copy
    before = fixture_snapshot()
    after = copy.deepcopy(before)
    after['tables']['alembic_version']['sha256'] = 'new-revision'
    guard.compare(before, after)
    for table in ('members', 'catalog_items', 'stock_items', 'audit_logs'):
        bad = copy.deepcopy(after)
        bad['tables'][table]['sha256'] = 'changed'
        with pytest.raises(guard.GuardError):
            guard.compare(before, bad)
    bad = copy.deepcopy(after)
    bad['roles'] = 'authority-changed'
    with pytest.raises(guard.GuardError):
        guard.compare(before, bad)
    bad = copy.deepcopy(after)
    bad['tables']['unexpected'] = {}
    with pytest.raises(guard.GuardError):
        guard.compare(before, bad)


def test_startup_failure_retains_api_and_evidence_without_stop_or_rollback(tmp_path, monkeypatch):
    import types
    import desktop_045_deploy as deploy
    calls = []
    class Driver:
        def __init__(self, stage, job):
            self.report = {'source_commit': 'a' * 40}
            self.job = tmp_path
            self.restores = []
            self.last_phase = 'start-verified-normal-api'
        def resume(self):
            calls.append('resume')
            raise deploy.DeploymentError('Health verification interrupted')
        def compose(self, *args):
            calls.append(args)
    monkeypatch.setattr(deploy, 'Desktop045', Driver)
    monkeypatch.setattr(deploy.os, 'name', 'posix')
    monkeypatch.setattr(deploy.os, 'getuid', lambda: 0, raising=False)
    monkeypatch.setattr(deploy.os, 'umask', lambda value: None)
    monkeypatch.setattr(deploy, 'no_links', lambda path: tmp_path / 'lock')
    monkeypatch.setitem(sys.modules, 'fcntl', types.SimpleNamespace(flock=lambda *args:None,LOCK_EX=1,LOCK_NB=2))
    monkeypatch.setattr(sys, 'argv', ['desktop_045_deploy.py','resume','--stage','fixture-stage',
                                     '--job','fixture-job','--commit','a'*40])
    assert deploy.main() == 1
    assert calls == ['resume']
