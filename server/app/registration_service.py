"""Database-serialized shared authorization, persistent limits and safe receipts."""
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from .api.errors import ApiError
from .audit_service import write_audit
from .auth_service import hash_password
from .business_barrier import shared_barrier
from .extensions import db
from .models import Employee, Terminal
from .registration_models import (
    RegistrationRateLimit, RegistrationReceipt, RegistrationTokenState, RegistrationTokenView,
)

ROLES = frozenset(('male_scrubber', 'female_scrubber', 'floor_attendant'))
FIELDS = frozenset(('username', 'display_name', 'role', 'password', 'code', 'terminal_code', 'client_channel'))


def utcnow():
    return datetime.now(timezone.utc)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _secret():
    value = current_app.config.get('REGISTRATION_TOKEN_SECRET', '')
    if not isinstance(value, str) or len(value.encode('utf-8')) < 32 or value.startswith('CHANGE_ME'):
        raise ApiError('注册授权尚未配置，请联系管理员', 503, 'REGISTRATION_NOT_CONFIGURED')
    return value.encode('utf-8')


def _digest(secret, domain, value):
    return hmac.new(secret, domain.encode('ascii') + b'\0' + value.encode('utf-8'), hashlib.sha256).hexdigest()


def derive_code(secret, generation, seed):
    digest = _digest(secret, 'registration-code-v1', f'{generation}:{seed}')
    return f'{int(digest, 16) % 1000000:06d}'


def _serialize_writes():
    connection = db.session.connection()
    # sqlite3 legacy reads do not start a physical transaction; acquire the
    # database write reservation before any service read. This works across
    # independent processes/connections, not just threads in the API worker.
    if connection.dialect.name == 'sqlite':
        raw = connection.connection.driver_connection
        if not raw.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            raise RuntimeError('Registration must acquire SQLite serialization before database writes')
    shared_barrier(connection)


def _locked_state():
    table = RegistrationTokenState.__table__
    values = dict(id=1, generation=1, seed=secrets.token_hex(32),
                  expires_at=utcnow() + timedelta(seconds=180), wrong_attempts=0)
    dialect = db.engine.dialect.name
    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise ApiError('注册授权数据库配置不支持', 503, 'REGISTRATION_NOT_CONFIGURED')
    inserted = db.session.execute(insert(table).values(**values).on_conflict_do_nothing(
        index_elements=['id'])).rowcount == 1
    state = RegistrationTokenState.query.populate_existing().filter_by(id=1).with_for_update().one()
    # An INSERT conflict or SELECT FOR UPDATE can wait beyond the code deadline.
    # The clock sampled after the lock governs expiry, verification and windows.
    now = utcnow()
    if inserted:
        state.expires_at = now + timedelta(seconds=180)
    return state, now


def _rotate(state, secret, now, reason, anonymous=False, terminal_id=None):
    old_code = derive_code(secret, state.generation, state.seed)
    previous = state.generation
    state.generation += 1
    while True:
        state.seed = secrets.token_hex(32)
        if derive_code(secret, state.generation, state.seed) != old_code:
            break
    state.expires_at = now + timedelta(seconds=180)
    state.wrong_attempts = 0
    write_audit('registration.token_rotated', 'registration_generation', str(state.generation),
                {'previous_generation': previous, 'generation': state.generation, 'reason': reason},
                anonymous=anonymous, terminal_id=terminal_id)


def current_token(employee, session_id):
    secret = _secret()
    _serialize_writes()
    # Recheck authorization after the write reservation, before generating state.
    from .registration_access import can_view_registration_token
    if not can_view_registration_token(employee, 'mobile'):
        raise ApiError('无权查看注册授权码', 403, 'REGISTRATION_FORBIDDEN')
    state, now = _locked_state()
    if now >= _utc(state.expires_at):
        _rotate(state, secret, now, 'expired')
    key = _digest(secret, 'registration-view-v1', f'{session_id}:{state.generation}')
    if db.session.get(RegistrationTokenView, key) is None:
        db.session.add(RegistrationTokenView(key=key, employee_id=employee.id, generation=state.generation))
        write_audit('registration.token_viewed', 'registration_generation', str(state.generation),
                    {'generation': state.generation, 'session_id': session_id}, employee_id=employee.id)
    result = dict(code=derive_code(secret, state.generation, state.seed), generation=state.generation,
                  server_time=now.isoformat(), expires_at=_utc(state.expires_at).isoformat())
    db.session.commit()
    return result


def validate_request(body, key):
    if (not isinstance(body, dict) or set(body) != FIELDS
            or any(not isinstance(value, str) for value in body.values())):
        raise ApiError('注册资料字段不正确', 400, 'INVALID_REGISTRATION_BODY')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,100}', key):
        raise ApiError('缺少有效的注册请求编号', 400, 'INVALID_IDEMPOTENCY_KEY')
    if body['client_channel'] != 'desktop':
        raise ApiError('仅允许通过电脑端注册', 403, 'REGISTRATION_FORBIDDEN')
    if not re.fullmatch(r'1[0-9]{10}', body['username']):
        raise ApiError('请输入正确的十一位手机号', 400, 'INVALID_REGISTRATION_BODY')
    if (not body['display_name'].strip() or len(body['display_name']) > 80
            or any(ord(char) < 32 for char in body['display_name']) or body['role'] not in ROLES
            or not re.fullmatch(r'[0-9]{6}', body['code'])
            or not 1 <= len(body['terminal_code']) <= 80):
        raise ApiError('姓名、岗位、授权码或终端资料不正确', 400, 'INVALID_REGISTRATION_BODY')
    if not 8 <= len(body['password']) <= 128:
        raise ApiError('密码需要 8–128 位', 400, 'WEAK_PASSWORD')


def _attempt_limit(secret, terminal_id, source, now):
    timestamp = now.timestamp()
    rows = []
    for domain, value in (('terminal', terminal_id), ('source', source)):
        key = _digest(secret, f'registration-limit-{domain}-v1', value)
        row = db.session.get(RegistrationRateLimit, key)
        if row is None:
            row = RegistrationRateLimit(key=key, attempts=[])
            db.session.add(row)
        row.attempts = [item for item in row.attempts if item > timestamp - 600]
        rows.append(row)
    if any(len(row.attempts) >= 10 for row in rows):
        return False
    for row in rows:
        row.attempts = [*row.attempts, timestamp]
    return True


def _reject(state, terminal, receipt_key, code, message, status=403):
    write_audit('registration.verification_failed', 'registration_generation', str(state.generation),
                {'generation': state.generation, 'request_key_digest': receipt_key, 'error_code': code},
                terminal_id=terminal.id, anonymous=True)
    db.session.commit()  # Failure budgets survive the response handler's rollback.
    raise ApiError(message, status, code)


def _receipt_identity(receipt, body):
    identity = receipt.identity
    expected = {'id': receipt.employee_id, 'username': body['username'],
                'display_name': body['display_name'].strip(), 'role': body['role'],
                'is_active': True, 'allowed_channels': ['desktop']}
    if (not isinstance(identity, dict) or set(identity) != set(expected)
            or identity != expected or type(identity.get('is_active')) is not bool):
        raise ApiError('注册回执资料不一致，请联系管理员', 409, 'IDEMPOTENCY_CONFLICT')
    return expected  # Return only service-defined fields, never arbitrary receipt JSON.


def register_employee(body, key, source):
    validate_request(body, key)
    secret = _secret()
    _serialize_writes()
    terminal = Terminal.query.filter_by(code=body['terminal_code'], is_active=True).first()
    if terminal is None:
        raise ApiError('终端未注册或已停用', 403, 'TERMINAL_INVALID')
    # Singleton lock serializes receipt lookup too, including simultaneous retries.
    state, now = _locked_state()
    receipt_key = _digest(secret, 'registration-receipt-v1', key)
    request_digest = _digest(secret, 'registration-request-v1',
                             json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    receipt = db.session.get(RegistrationReceipt, receipt_key)
    if receipt:
        if receipt.terminal_id != terminal.id or not hmac.compare_digest(receipt.request_digest, request_digest):
            raise ApiError('注册请求编号已用于其他资料', 409, 'IDEMPOTENCY_CONFLICT')
        identity = _receipt_identity(receipt, body)
        db.session.commit()
        return identity
    if now >= _utc(state.expires_at):
        _rotate(state, secret, now, 'expired', anonymous=True, terminal_id=terminal.id)
    if not _attempt_limit(secret, terminal.id, source or '', now) or state.wrong_attempts >= 5:
        _reject(state, terminal, receipt_key, 'REGISTRATION_RATE_LIMITED', '注册尝试过于频繁，请稍后重试', 429)
    if not hmac.compare_digest(body['code'], derive_code(secret, state.generation, state.seed)):
        state.wrong_attempts += 1
        _reject(state, terminal, receipt_key, 'REGISTRATION_CODE_INVALID', '注册授权码已失效或不正确')
    if Employee.query.filter_by(username=body['username']).first():
        _reject(state, terminal, receipt_key, 'USERNAME_EXISTS', '该手机号已有账号，请联系管理员', 409)
    employee = Employee(username=body['username'], display_name=body['display_name'].strip(),
        role=body['role'], password_hash=hash_password(body['password']), is_active=True,
        allowed_channels=['desktop'], mobile_full_access=False)
    db.session.add(employee)
    db.session.flush()
    identity = {name: getattr(employee, name) for name in ('id', 'username', 'display_name', 'role', 'is_active')}
    identity['allowed_channels'] = ['desktop']
    generation = state.generation
    state.consumed_generation = generation
    state.consumed_at = now
    _rotate(state, secret, now, 'consumed', anonymous=True, terminal_id=terminal.id)
    db.session.add(RegistrationReceipt(key=receipt_key, terminal_id=terminal.id, request_digest=request_digest,
        employee_id=employee.id, generation=generation, identity=identity))
    write_audit('registration.employee_created', 'employee', employee.id,
        {'generation': generation, 'request_key_digest': receipt_key, 'new_employee_id': employee.id},
        terminal_id=terminal.id, anonymous=True)
    db.session.commit()
    return identity
