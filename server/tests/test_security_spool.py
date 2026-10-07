import json

import pytest


def test_private_spool_imports_real_audit_once_and_rejects_tampering(app, tmp_path):
    from app import security_spool
    from app.audit_service import verify_audit_chain
    from app.extensions import db
    from app.models import AuditLog
    app.config['RESET_PRIVATE_DIR'] = str(tmp_path / 'private')
    event_id = security_spool.write_security_event({'action': 'security.request_denied',
        'details': {'error_code': 'BUSINESS_MAINTENANCE'}})
    files = list((tmp_path / 'private' / 'spool').glob('*.json'))
    assert len(files) == 1
    saved = files[0].read_bytes()
    assert security_spool.import_spool_events() == 1
    assert AuditLog.query.filter_by(entity_id=event_id).count() == 1
    files[0].write_bytes(saved)  # Simulate crash after commit, before unlink.
    assert security_spool.import_spool_events() == 0
    assert AuditLog.query.filter_by(entity_id=event_id).count() == 1
    assert verify_audit_chain() == (True, None)
    security_spool.write_security_event({'details': {'status': 503}})
    path = next((tmp_path / 'private' / 'spool').glob('*.json'))
    content = json.loads(path.read_text())
    content['event']['details']['status'] = 200
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match='integrity'):
        security_spool.import_spool_events()
    assert path.exists()
    db.session.rollback()


def test_spool_preserves_original_request_attribution_and_failed_import(app, tmp_path):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.extensions import db
    from app.models import AuditLog
    from app.security_spool import import_spool_events, write_security_event
    app.config['RESET_PRIVATE_DIR'] = str(tmp_path / 'private')
    event_id = write_security_event({'request_id': 'original-request-id',
        'context': {'method': 'POST', 'path': '/api/auth/login', 'source_ip': '127.0.0.2'},
        'details': {'status': 503, 'error_code': 'BUSINESS_MAINTENANCE'}})
    with db.engine.begin() as connection:
        connection.execute(text("CREATE TRIGGER reject_import BEFORE INSERT ON audit_logs "
                                "BEGIN SELECT RAISE(ABORT, 'interrupt import'); END"))
    with pytest.raises(IntegrityError, match='interrupt import'):
        import_spool_events()
    assert len(list((tmp_path / 'private' / 'spool').glob('*.json'))) == 1
    with db.engine.begin() as connection:
        connection.execute(text('DROP TRIGGER reject_import'))
    assert import_spool_events() == 1
    record = db.session.get(AuditLog, event_id)
    assert record.request_id == 'original-request-id'
    assert record.context['path'] == '/api/auth/login'
    assert record.context['source_ip'] == '127.0.0.2'
