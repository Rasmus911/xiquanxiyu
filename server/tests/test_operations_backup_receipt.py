"""Breaks caught: forged restore status, changed dump or stale business snapshot."""
import hashlib
import json
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import BusinessStateModel


@pytest.fixture()
def receipt(app, tmp_path):
    from app.operations_backup import snapshot_identity
    app.config['RESET_PRIVATE_DIR'] = str(tmp_path / 'private')
    from app.reset_backup import private_directory
    root = private_directory('receipts')
    dump = root / 'test.backup'
    dump.write_bytes(b'fixture-is-not-a-real-postgresql-backup')
    dump.chmod(0o600)
    with db.engine.connect() as connection:
        identity = snapshot_identity(connection)
    data = dict(schema=1, dump_path=str(dump), dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
        dump_size=dump.stat().st_size, **identity, restore=dict(status='verified', pg_major=17,
        checked_at=datetime.now(timezone.utc).isoformat(), checks_sha256='a'*64))
    path = root / 'receipt.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    path.chmod(0o600)
    return path, data, dump


def save(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')


def test_receipt_matches_actual_dump_and_current_snapshot(app, receipt):
    from app.operations_backup import validate_backup_receipt
    path, data, _ = receipt
    with db.engine.connect() as connection:
        assert validate_backup_receipt(connection, path, 'metadata-create-all')['dump_sha256'] == data['dump_sha256']


@pytest.mark.parametrize('change', ['list-only','missing-restore','wrong-major','invalid-checks',
    'wrong-revision','wrong-database','wrong-period','wrong-business-revision','wrong-audit','wrong-size','wrong-hash'])
def test_receipt_rejects_unverified_or_stale_evidence(app, receipt, change):
    from app.operations_backup import BackupReceiptError, validate_backup_receipt
    path, data, _ = receipt
    if change == 'list-only': data['restore']['status'] = 'list-only'
    elif change == 'missing-restore': del data['restore']
    elif change == 'wrong-major': data['restore']['pg_major'] = 16
    elif change == 'invalid-checks': data['restore']['checks_sha256'] = 'not-a-hash'
    elif change == 'wrong-revision': data['alembic_revision'] = 'older'
    elif change == 'wrong-database': data['db_name'] = 'other'
    elif change == 'wrong-period': data['business_period_id'] = 'other'
    elif change == 'wrong-business-revision': data['business_revision'] += 1
    elif change == 'wrong-audit': data['audit_checkpoint']['chain_index'] += 1
    elif change == 'wrong-size': data['dump_size'] += 1
    elif change == 'wrong-hash': data['dump_sha256'] = '0'*64
    save(path, data)
    with db.engine.connect() as connection, pytest.raises(BackupReceiptError):
        validate_backup_receipt(connection, path, 'metadata-create-all')


def test_receipt_rejects_changed_bytes_and_public_path(app, receipt, tmp_path):
    from app.operations_backup import BackupReceiptError, validate_backup_receipt
    path, _, dump = receipt
    dump.write_bytes(b'changed')
    with db.engine.connect() as connection, pytest.raises(BackupReceiptError):
        validate_backup_receipt(connection, path, 'metadata-create-all')
    public = tmp_path / 'public.json'
    public.write_text(path.read_text(), encoding='utf-8')
    with db.engine.connect() as connection, pytest.raises(BackupReceiptError):
        validate_backup_receipt(connection, public, 'metadata-create-all')


def test_receipt_rejects_database_changed_after_backup(app, receipt):
    from app.operations_backup import BackupReceiptError, validate_backup_receipt
    path, _, _ = receipt
    state = db.session.get(BusinessStateModel, 1)
    state.business_revision += 1
    db.session.commit()
    with db.engine.connect() as connection, pytest.raises(BackupReceiptError):
        validate_backup_receipt(connection, path, 'metadata-create-all')


def test_private_evidence_rejects_parent_traversal(app, receipt, tmp_path, monkeypatch):
    from app.operations_backup import BackupReceiptError, private_path
    path, _data, _dump = receipt
    outside = path.parent.parent.parent / 'outside.json'
    outside.write_text('{}', encoding='utf-8')
    outside.chmod(0o600)
    # Path confinement must not depend on the escaped file having an unsafe ACL.
    monkeypatch.setattr('app.operations_backup._check_windows_acl', lambda _path: None)
    escaped = path.parent / '..' / '..' / 'outside.json'
    with pytest.raises(BackupReceiptError): private_path(escaped)


def test_private_evidence_rejects_broad_readers(app, receipt):
    import os
    import subprocess
    from app.operations_backup import BackupReceiptError, private_path
    path, _data, _dump = receipt
    if os.name == 'nt':
        subprocess.run(['icacls',str(path),'/grant','*S-1-5-32-545:R'],capture_output=True,check=True)
    else: path.chmod(0o644)
    with pytest.raises(BackupReceiptError): private_path(path)
