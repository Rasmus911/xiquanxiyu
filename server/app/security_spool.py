"""Durable signed rejection evidence while the business database is unavailable."""
import hmac
import json
import os

from flask import current_app

from .audit_service import sign_evidence, write_audit
from .extensions import db
from .models import AuditLog, new_uuid, utcnow
from .reset_backup import private_directory


def write_security_event(event):
    event_id = new_uuid()
    # Explicit whitelist prevents accidentally persisting credentials or request bodies.
    evidence = {'id': event_id, 'created_at': utcnow().isoformat(),
                'action': 'security.request_denied',
                'details': {key: value for key, value in event.get('details', {}).items()
                            if key in {'status', 'error_code', 'attempted_username'}},
                'request_id': event.get('request_id'), 'employee_id': event.get('employee_id'),
                'terminal_id': event.get('terminal_id'),
                'context': {key: value for key, value in event.get('context', {}).items()
                            if key in {'source_ip', 'method', 'path', 'session_id', 'identity_verified'}}}
    envelope = {'event': evidence, 'signature': sign_evidence(evidence)}
    path = private_directory('spool') / f'{event_id}.json'
    temporary = path.with_suffix('.partial')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(envelope, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return event_id


def import_spool_events():
    count = 0
    for path in sorted(private_directory('spool').glob('*.json')):
        try:
            envelope = json.loads(path.read_text(encoding='utf-8'))
            evidence = envelope['event']
            if not hmac.compare_digest(str(envelope['signature']), sign_evidence(evidence)):
                raise ValueError('security spool integrity failure')
            # Deterministic audit UUID is an additional uniqueness boundary against
            # concurrent import/crash replay, independent of process-local state.
            if not db.session.get(AuditLog, evidence['id']):
                write_audit('security.request_denied', 'security_spool', evidence['id'], evidence,
                            record_id=evidence['id'], original_context=evidence.get('context'),
                            original_request_id=evidence.get('request_id'),
                            employee_id=evidence.get('employee_id'), terminal_id=evidence.get('terminal_id'))
                db.session.commit()
                count += 1
            else:
                db.session.rollback()
            path.unlink()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Security spool import failed; evidence retained')
            raise
    return count
