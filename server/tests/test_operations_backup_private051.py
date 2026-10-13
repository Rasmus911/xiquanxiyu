"""051 opt-in diagnostics catch inner failures before legacy public masking."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.engine import make_url


@pytest.fixture
def maintenance(tmp_path):
    from app.operations_backup import register_operations_backup_cli
    from app.reset_backup import private_directory
    app = Flask('backup-private-proof', static_folder=None)
    app.config.update(MAINTENANCE_PROCESS=True, RESET_PRIVATE_DIR=str(tmp_path / 'private'),
        RESET_BACKUP_DATABASE_URL='postgresql+psycopg://backup:hidden@postgres/bathhouse',
        PG_DUMP_PATH='pg_dump', PG_RESTORE_PATH='pg_restore')
    register_operations_backup_cli(app)
    with app.app_context():
        yield app, private_directory('diagnostics')


@pytest.mark.parametrize('boundary,code,category', [('version', None, 'timeout'),
    ('dump', 137, 'sigkill137'), ('list', 2, 'exit')])
def test_inner_backup_failure_is_private_and_public_cli_stays_sanitized(maintenance, monkeypatch, boundary, code, category):
    from app import operations_backup as backup
    app, root = maintenance
    evidence = root / ('backup-diagnostic-' + 'a' * 32 + '.json')
    original_run, original_open = subprocess.run, os.open
    modes = []
    def run(argv, **kwargs):
        if argv[0] not in ('pg_dump', 'pg_restore'): return original_run(argv, **kwargs)
        stage = 'version' if '--version' in argv else 'list' if '--list' in argv else 'dump'
        if stage == boundary:
            if code is None: raise subprocess.TimeoutExpired(argv, kwargs['timeout'], output=b'partial', stderr=b'private-auth-reason')
            raise subprocess.CalledProcessError(code, argv, output=b'partial', stderr=b'private-auth-reason')
        return subprocess.CompletedProcess(argv, 0, stdout='pg_dump (PostgreSQL) 17.11', stderr='')
    def opened(path, flags, mode=0o777):
        if Path(path) == evidence: modes.append((flags, mode))
        return original_open(path, flags, mode)
    def create(output, *, diagnostic=None):
        return backup.run_snapshot_dump(make_url('postgresql+psycopg://owner:hidden@postgres/bathhouse'),
            '00000005-000000E4-1', root / 'database.backup', diagnostic=diagnostic)
    monkeypatch.setattr(backup.subprocess, 'run', run)
    monkeypatch.setattr(backup.os, 'open', opened)
    monkeypatch.setattr(backup, 'create_operations_snapshot', create)
    result = app.test_cli_runner().invoke(args=['operations-backup', 'create', '--output', str(root),
        '--private-evidence', str(evidence)])
    assert result.exit_code == 1 and 'private-auth-reason' not in result.output and 'hidden' not in result.output
    assert 'category=' + category in result.output
    record = json.loads(evidence.read_text(encoding='utf-8'))
    assert record['category'] == category and record['exit_code'] == code
    assert record['stderr'] == 'private-auth-reason' and record['stdout'] == 'partial'
    assert record['boundary'] == 'snapshot-dump' and record['command'][0] in ('pg_dump', 'pg_restore')
    assert modes == [(os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)]


def test_private_diagnostics_are_not_enabled_in_normal_api_cli(maintenance):
    app, root = maintenance
    app.config['MAINTENANCE_PROCESS'] = False
    evidence = root / ('backup-diagnostic-' + 'b' * 32 + '.json')
    result = app.test_cli_runner().invoke(args=['operations-backup', 'create', '--output', str(root),
        '--private-evidence', str(evidence)])
    assert result.exit_code != 0 and 'maintenance' in result.output.lower()
    assert not evidence.exists()


def test_restore_verification_retains_inner_original_before_masking(maintenance, monkeypatch):
    from app import operations_backup as backup
    app, root = maintenance
    dump = root / 'database.backup'
    dump.write_bytes(b'isolated fixture')
    dump.chmod(0o600)
    candidate = root / 'candidate.json'
    digest, size = backup.file_digest(dump)
    backup.write_private_json(candidate, dict(dump_path=str(dump), dump_sha256=digest, dump_size=size))
    def fail_engine(*args, **kwargs): raise RuntimeError('private-original-connection-reason')
    monkeypatch.setattr(backup, 'create_engine', fail_engine)
    monkeypatch.setenv('XIQUAN_RESTORE_DATABASE_URL', 'postgresql+psycopg://owner:hidden@clone/restore')
    evidence = root / ('backup-diagnostic-' + 'c' * 32 + '.json')
    result = app.test_cli_runner().invoke(args=['operations-backup', 'verify-restored',
        '--receipt', str(candidate), '--database-url-env', 'XIQUAN_RESTORE_DATABASE_URL', '--private-evidence', str(evidence)])
    assert result.exit_code == 1 and 'private-original' not in result.output
    record = json.loads(evidence.read_text(encoding='utf-8'))
    assert record['boundary'] == 'restore-verification'
    assert 'private-original-connection-reason' in record['traceback']
    assert not (root / 'receipt.json').exists()
