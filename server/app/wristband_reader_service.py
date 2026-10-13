"""Cloud-owned physical identities. Caller holds the financial transaction lock."""
import re
from datetime import timedelta, timezone

from flask_jwt_extended import get_jwt

from .api.errors import ApiError
from .api.wristbands import _active_visit, _create_visit, _require_current_band
from .audit_service import write_audit
from .extensions import db
from .models import Visit, Wristband, WristbandChipBinding, WristbandScanSession, new_uuid, utcnow

CURRENT_BAND_NUMBERS = frozenset(f'{number:03}' for number in range(1, 101))


def current_physical_band(band):
    _require_current_band(band)
    if band.number not in CURRENT_BAND_NUMBERS:
        raise ApiError('芯片录入仅支持当前 001–100 手牌', 409, 'WRISTBAND_NOT_CURRENT')


def chip_uid(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,64}', value.strip()):
        raise ApiError('芯片 ID 必须是 1–64 位数字', 400, 'INVALID_CHIP_UID')
    return value.strip()


def binding_data(band, binding=None):
    return {'wristband_id': band.id, 'number': band.number, 'bath_area': band.bath_area,
            'status': band.status, 'chip_uid': binding.chip_uid if binding else None,
            'version': binding.version if binding else 0,
            'updated_at': binding.updated_at.isoformat() if binding else None}


def change_binding(employee, terminal_id, band_id, body, deleting=False):
    from .auth_service import verify_sensitive_password
    allowed = {'version', 'password'} | (set() if deleting else {'chip_uid'})
    if set(body) - allowed:
        raise ApiError('不支持的录入参数')
    band = Wristband.query.filter_by(id=band_id).with_for_update().first()
    if not band:
        raise ApiError('手牌不存在', 404, 'NOT_FOUND')
    current_physical_band(band)
    if band.status != 'available' or _active_visit(band.id, lock=True):
        raise ApiError('只能修改空闲手牌的芯片绑定', 409, 'WRISTBAND_NOT_AVAILABLE')
    row = WristbandChipBinding.query.filter_by(wristband_id=band.id).with_for_update().first()
    version = body.get('version')
    if type(version) is not int or version != (row.version if row else 0):
        raise ApiError('绑定已变更，请刷新后重新录入', 409, 'BINDING_CHANGED')
    uid = None if deleting else chip_uid(body.get('chip_uid'))
    old = row.chip_uid if row else None
    if row and uid == old and not deleting:
        return binding_data(band, row)
    if row or deleting:
        password = body.get('password')
        if not isinstance(password, str):
            raise ApiError('请验证当前登录账号的密码', 403, 'REAUTH_REQUIRED')
        verify_sensitive_password(employee, password)
    if deleting and not old:
        raise ApiError('该手牌未绑定芯片', 409, 'CHIP_NOT_BOUND')
    if uid and WristbandChipBinding.query.filter(
            WristbandChipBinding.chip_uid == uid, WristbandChipBinding.wristband_id != band.id).first():
        raise ApiError('该芯片已绑定其他手牌', 409, 'CHIP_ALREADY_BOUND')
    if row is None:
        row = WristbandChipBinding(wristband_id=band.id, chip_uid=uid,
            changed_by_id=employee.id, changed_terminal_id=terminal_id)
        db.session.add(row)
    else:
        row.chip_uid = uid
        row.changed_by_id = employee.id
        row.changed_terminal_id = terminal_id
        row.version += 1
    db.session.flush()
    write_audit('wristband.chip_unbind' if deleting else 'wristband.chip_bind', 'wristband', band.id,
        {'wristband_number': band.number, 'previous_chip_uid': old, 'chip_uid': uid,
         'binding_version': row.version})
    return binding_data(band, row)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _scan_session(employee, terminal_id, identifier, now):
    if identifier is None:
        return None
    if not isinstance(identifier, str) or len(identifier) > 36:
        raise ApiError('刷卡联动会话无效', 400, 'INVALID_SCAN_SESSION')
    row = WristbandScanSession.query.filter_by(id=identifier).with_for_update().first()
    if (not row or row.employee_id != employee.id or row.terminal_id != terminal_id
            or row.auth_session_id != get_jwt().get('session_id')):
        raise ApiError('刷卡会话不属于当前账号或终端', 403, 'SCAN_SESSION_FORBIDDEN')
    if row.closed_at:
        return None
    valid = _utc(row.expires_at) > now
    visits = Visit.query.filter_by(party_id=row.party_id).order_by(Visit.id).with_for_update().all()
    if {visit.id for visit in visits} != set(row.members):
        valid = False
    bands = {band.id: band for band in Wristband.query.filter(
        Wristband.id.in_([visit.wristband_id for visit in visits])).order_by(Wristband.id).with_for_update().all()}
    for visit in visits:
        member = row.members.get(visit.id, {})
        band = bands.get(visit.wristband_id)
        if (visit.status != 'open' or visit.wristband_id != member.get('wristband_id')
                or visit.version != member.get('version') or not band or not band.is_active or band.status != 'in_use'):
            valid = False
    if not valid:
        row.closed_at = now
        row.version += 1
        return None
    return row


def _session_data(row):
    if row is None:
        return None
    band_ids = [member['wristband_id'] for member in row.members.values()]
    numbers = [band.number for band in Wristband.query.filter(Wristband.id.in_(band_ids)).order_by(Wristband.number).all()]
    return {'id': row.id, 'expires_at': _utc(row.expires_at).isoformat(), 'numbers': numbers}


def scan_wristband(employee, body):
    from .idempotency_service import idempotency_lookup, idempotency_store, idempotency_record_key
    if set(body) - {'chip_uid', 'link_mode', 'session_id', 'idempotency_key'}:
        raise ApiError('刷卡开牌不接受金额或其他业务参数')
    uid = chip_uid(body.get('chip_uid'))
    link = body.get('link_mode')
    key = body.get('idempotency_key')
    if type(link) is not bool or not isinstance(key, str) or not 8 <= len(key) <= 100:
        raise ApiError('刷卡模式或请求编号无效')
    if not link and body.get('session_id'):
        raise ApiError('独立开牌不能指定联动会话')
    endpoint = 'wristband-reader.scan'
    replay = idempotency_lookup(endpoint, employee.id, key)
    if replay:
        return {k: v for k, v in replay.response_body.items() if k != '_request_hash'}
    binding = WristbandChipBinding.query.filter_by(chip_uid=uid).first()
    if binding is None:
        raise ApiError('芯片未录入，请先在手牌 ID 录入页面绑定', 404, 'CHIP_NOT_BOUND')
    band = Wristband.query.filter_by(id=binding.wristband_id).with_for_update().one()
    current_physical_band(band)
    now = _utc(utcnow())
    terminal_id = get_jwt()['terminal_id']
    session = _scan_session(employee, terminal_id, body.get('session_id'), now) if link else None
    visit = _active_visit(band.id, lock=True)
    opened = False
    if band.status == 'in_use' and visit and visit.status == 'open':
        # Never adopt a pre-existing customer or extend its receiving deadline.
        pass
    elif band.status != 'available' or visit:
        raise ApiError('手牌正在挂失、停用或结算中，不能刷卡开牌', 409, 'WRISTBAND_NOT_AVAILABLE')
    else:
        if link and session is None:
            session = WristbandScanSession(employee_id=employee.id, terminal_id=terminal_id,
                auth_session_id=get_jwt()['session_id'],
                party_id=new_uuid(), expires_at=now + timedelta(seconds=60), members={})
            db.session.add(session)
        if session and len(session.members) >= 100:
            raise ApiError('当前联动组已满，请结束联动后重新刷卡', 409, 'SCAN_GROUP_FULL')
        visit, ticket = _create_visit(band, employee, party_id=session.party_id if session else None)
        if session:
            session.members = {**session.members, visit.id: {'wristband_id': band.id, 'version': visit.version}}
            session.expires_at = now + timedelta(seconds=60)
            session.version += 1
        db.session.flush()
        write_audit('wristband.chip_open', 'visit', visit.id,
            {'wristband_number': band.number, 'chip_uid': uid, 'ticket_price': str(ticket.unit_price),
             'party_id': visit.party_id, 'scan_session_id': session.id if session else None})
        opened = True
    result = {'opened': opened, 'wristband_number': band.number, 'visit_id': visit.id,
              'session': _session_data(session), 'server_time': now.isoformat()}
    idempotency_store(idempotency_record_key(endpoint, employee.id, key), endpoint, 200, result)
    return result
