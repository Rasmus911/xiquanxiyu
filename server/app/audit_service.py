import hashlib
import hmac
import json
from datetime import timezone

from flask import current_app, g, has_request_context, request
from flask_jwt_extended import get_jwt
from sqlalchemy import text

from .extensions import db
from .models import AuditLog, Employee, Terminal, new_uuid, utcnow


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _timestamp(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def sign_evidence(payload):
    secret = current_app.config.get("AUDIT_HMAC_KEY")
    if not secret:
        secret = hmac.new(
            str(current_app.config["JWT_SECRET_KEY"]).encode(),
            b"xiquan-audit-v2",
            hashlib.sha256,
        ).hexdigest()
    return hmac.new(str(secret).encode(), _canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()


def _payload(item):
    result = {
        key: getattr(item, key)
        for key in (
            "chain_index",
            "employee_id",
            "terminal_id",
            "action",
            "entity_type",
            "entity_id",
            "details",
            "request_id",
            "prev_hash",
        )
    }
    if item.integrity_version == 2:
        result.update(id=item.id, integrity_version=2, context=item.context, created_at=_timestamp(item.created_at))
    return result


def lock_audit_chain():
    if db.engine.dialect.name == "postgresql":
        db.session.execute(text("SELECT pg_advisory_xact_lock(713829416)"))


def write_audit(action, entity_type, entity_id, details, employee_id=None, terminal_id=None,
                record_id=None, session=None, original_context=None, original_request_id=None):
    session = session or db.session
    from .business_barrier import shared_barrier
    shared_barrier(session.connection())
    claims = {}
    try:
        claims = get_jwt()
    except RuntimeError:
        pass
    employee_id = employee_id or claims.get("sub") or getattr(g, "audit_employee_id", None)
    terminal_id = terminal_id or claims.get("terminal_id") or getattr(g, "audit_terminal_id", None)
    employee = session.get(Employee, employee_id) if employee_id else None
    terminal = session.get(Terminal, terminal_id) if terminal_id else None
    if session.get_bind().dialect.name == 'postgresql':
        session.execute(text('SELECT pg_advisory_xact_lock(713829416)'))
    last = session.query(AuditLog).order_by(AuditLog.chain_index.desc()).first()
    context = {
        "employee_username": employee.username if employee else "系统/未登录",
        "employee_name": employee.display_name if employee else None,
        "employee_role": employee.role if employee else None,
        "terminal_code": terminal.code if terminal else None,
        "terminal_name": terminal.name if terminal else None,
        "session_id": claims.get("session_id") or getattr(g, "audit_session_id", None),
        "identity_verified": bool(getattr(g, "audit_authenticated", False)),
    }
    if has_request_context():
        context.update(
            source_ip=request.remote_addr,
            method=request.method,
            path=request.path,
            user_agent=request.headers.get("User-Agent", "")[:400],
            client_type_claim=request.headers.get("X-Client-Type", "")[:40],
            client_version_claim=request.headers.get("X-Client-Version", "")[:40],
        )
    if original_context is not None:
        context = original_context
    record = AuditLog(
        id=record_id or new_uuid(),
        created_at=utcnow(),
        integrity_version=2,
        context=context,
        chain_index=1 if last is None else last.chain_index + 1,
        prev_hash="0" * 64 if last is None else last.current_hash,
        employee_id=employee_id,
        terminal_id=terminal_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        request_id=original_request_id or getattr(g, "request_id", None),
    )
    record.current_hash = sign_evidence(_payload(record))
    session.add(record)
    session.flush()
    return record


def verify_audit_chain() -> tuple[bool, int | None]:
    previous_hash = "0" * 64
    expected_index = 1
    strong_seen = False
    for item in AuditLog.query.order_by(AuditLog.chain_index.asc()).yield_per(500):
        if item.integrity_version == 2:
            strong_seen = True
            actual = sign_evidence(_payload(item))
        elif item.integrity_version == 1 and not strong_seen:
            actual = hashlib.sha256(_canonical_json(_payload(item)).encode("utf-8")).hexdigest()
        else:
            return False, item.chain_index
        if (
            item.chain_index != expected_index
            or item.prev_hash != previous_hash
            or not hmac.compare_digest(item.current_hash, actual)
        ):
            return False, item.chain_index
        previous_hash = item.current_hash
        expected_index += 1
    return True, None


def record_rejected_request(response):
    if response.status_code < 400 or request.method == "OPTIONS" or not request.path.startswith("/api/"):
        return response
    db.session.rollback()
    payload = response.get_json(silent=True) or {}
    details = {"status": response.status_code, "error_code": (payload.get("error") or {}).get("code", "HTTP_ERROR")}
    if request.path == "/api/auth/login":
        try:
            body = request.get_json(silent=True)
            details["attempted_username"] = str(body.get("username", ""))[:50] if isinstance(body, dict) else ""
        except Exception:
            details["attempted_username"] = "(请求内容不可读取)"
    try:
        from .business_barrier import shared_barrier
        shared_barrier(db.session.connection())
        write_audit("security.request_denied", "request", getattr(g, "request_id", None), details)
        db.session.commit()
    except Exception:
        db.session.rollback()
        from .security_spool import write_security_event
        try:
            write_security_event({'details': details, 'request_id': getattr(g, 'request_id', None),
                'employee_id': getattr(g, 'audit_employee_id', None),
                'terminal_id': getattr(g, 'audit_terminal_id', None),
                'context': {'source_ip': request.remote_addr, 'method': request.method, 'path': request.path,
                    'identity_verified': bool(getattr(g, 'audit_authenticated', False)),
                    'session_id': getattr(g, 'audit_session_id', None)}})
        except Exception:
            current_app.logger.exception('Security audit and private spool both unavailable')
    return response
