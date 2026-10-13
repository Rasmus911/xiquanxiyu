"""Physical card identifiers are opaque decimal text, never numeric values."""
import re
from datetime import date

from .api.errors import ApiError
from .audit_service import write_audit
from .auth_service import verify_sensitive_password
from .extensions import db
from .financial_lock import serialize_financial_session
from .idempotency_service import (financial_request_key, idempotency_lookup,
                                  idempotency_record_key, idempotency_store)
from .member_card_models import MemberCardBinding
from .models import Member, MemberPass, PassLedger, StoredValueLedger, utcnow
from .serializers import member_card_binding_dict, member_dict
from .validation import decimal_value, integer_value


def normalize_card_uid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('卡号必须是数字文本')
    uid = value.strip()
    if not re.fullmatch(r'[0-9]{1,64}', uid):
        raise ValueError('卡号应为1至64位数字')
    return uid


def normalize_phone(value):
    phone = re.sub(r'\D', '', str(value or ''))
    if len(phone) != 11:
        raise ApiError('请输入 11 位手机号')
    return phone


def card_uid_value(value):
    try:
        return normalize_card_uid(value)
    except ValueError as error:
        raise ApiError(str(error), code='INVALID_CARD_UID') from None


def member_pass_dict(row):
    return {'id': row.id, 'name': row.name, 'remaining_count': row.remaining_count,
            'valid_until': row.valid_until.isoformat() if row.valid_until else None,
            'is_active': row.is_active}


def physical_request_key(payload):
    key = str(payload.get('idempotency_key') or '').strip()
    if not key:
        raise ApiError('缺少幂等请求编号', code='IDEMPOTENCY_REQUIRED')
    if len(key) > 100:
        raise ApiError('请求编号过长')
    return key


def _unused_card(uid):
    previous = MemberCardBinding.query.filter_by(card_uid=uid).with_for_update().first()
    if previous:
        if not previous.is_active:
            raise ApiError('此实体卡已作废，请使用新卡', 409, 'CARD_REVOKED')
        raise ApiError('此实体卡已绑定会员，请先查询', 409, 'CARD_IN_USE')


def _capture(endpoint, employee, key, data, status):
    # Records are immutable. Under the financial lock, INSERT only the final result.
    idempotency_store(idempotency_record_key(endpoint, employee.id, key),
                      endpoint, status, {'data': data})
    db.session.flush()
    return data


def open_physical_member(employee, terminal, payload) -> dict:
    """Record a confirmed paid opening; caller commits all rows together."""
    serialize_financial_session(db.session)
    endpoint = 'members:physical-open'
    key = physical_request_key(payload)
    existing = idempotency_lookup(endpoint, employee.id, key)
    if existing:
        return existing.response_body['data']
    uid = card_uid_value(payload.get('card_uid'))
    phone = normalize_phone(payload['phone']) if payload.get('phone') else None
    surname = str(payload.get('holder_surname') or '').strip() or None
    if surname and (payload.get('surname_confirmed') is not True or len(surname) > 40):
        raise ApiError('持卡人姓氏需核实确认，且不超过40字', code='SURNAME_UNCONFIRMED')
    card_type = payload.get('membership_type')
    if card_type not in ('stored', 'pass'):
        raise ApiError('会员卡类型无效')
    amount = decimal_value(payload.get('amount'), '金额', positive=True)
    payment_method = payload.get('payment_method')
    if payment_method not in ('cash', 'wechat', 'alipay'):
        raise ApiError('开卡支付方式无效')
    count, valid_until, pass_name = None, None, None
    if card_type == 'pass':
        count = integer_value(payload.get('count'), '次卡次数')
        try:
            valid_until = date.fromisoformat(payload['valid_until']) if payload.get('valid_until') else None
        except (TypeError, ValueError):
            raise ApiError('次卡有效期需要是正确的 YYYY-MM-DD 日期', code='INVALID_DATE') from None
        pass_name = str(payload.get('pass_name') or '').strip() or '洗浴次卡'
        if len(pass_name) > 100:
            raise ApiError('次卡名称不能超过100字')
    # Phone conflicts include inactive accounts: operators must query/bind explicitly.
    if phone and Member.query.filter_by(phone=phone).with_for_update().first():
        raise ApiError('手机号已经注册，请先查询会员并绑定实体卡', 409, 'PHONE_EXISTS')
    _unused_card(uid)
    member = Member(phone=phone, holder_surname=surname,
                    balance=amount if card_type == 'stored' else 0)
    db.session.add(member)
    db.session.flush()
    binding = MemberCardBinding(member_id=member.id, card_uid=uid,
                                created_by=employee.id, terminal_id=terminal.id)
    db.session.add(binding)
    ledger_key = financial_request_key(endpoint, employee.id, key)
    member_pass = None
    if card_type == 'stored':
        db.session.add(StoredValueLedger(member_id=member.id, amount=amount, balance_after=amount,
            entry_type='recharge', payment_method=payment_method, operator_id=employee.id,
            idempotency_key=ledger_key))
    else:
        member_pass = MemberPass(member_id=member.id, name=pass_name,
                                 remaining_count=count, valid_until=valid_until)
        db.session.add(member_pass)
        db.session.flush()
        db.session.add(PassLedger(member_pass_id=member_pass.id, delta=count, balance_after=count,
            entry_type='issue', amount_paid=amount, payment_method=payment_method,
            operator_id=employee.id, idempotency_key=ledger_key))
    db.session.flush()
    data = {'member': member_dict(member), 'card_binding': member_card_binding_dict(binding),
            'member_pass': member_pass_dict(member_pass) if member_pass else None}
    write_audit('member.physical_open', 'member', member.id,
        {**data, 'membership_type': card_type, 'amount': str(amount),
         'payment_method': payment_method}, employee_id=employee.id, terminal_id=terminal.id)
    return _capture(endpoint, employee, key, data, 201)


def bind_physical_card(member, employee, terminal, payload) -> dict:
    """Bind/replace without changing account rights; caller owns commit."""
    serialize_financial_session(db.session)
    endpoint = f'members:{member.id}:physical-card'
    key = physical_request_key(payload)
    existing = idempotency_lookup(endpoint, employee.id, key)
    if existing:
        return existing.response_body['data']
    # Failed reauthentication commits its counter; no placeholder/mutation yet.
    verify_sensitive_password(employee, str(payload.get('password') or ''))
    member = Member.query.filter_by(id=member.id, is_active=True).filter(
        Member.deleted_at.is_(None)).with_for_update().first()
    if not member:
        raise ApiError('会员不存在或已归档停用', 404, 'MEMBER_NOT_FOUND')
    uid = card_uid_value(payload.get('card_uid'))
    _unused_card(uid)
    old = MemberCardBinding.query.filter_by(member_id=member.id, is_active=True).with_for_update().first()
    if old:
        old.is_active = False
        old.revoked_at = utcnow()
        old.version += 1
        db.session.flush()  # Release the one-active-card uniqueness before INSERT.
    binding = MemberCardBinding(member_id=member.id, card_uid=uid,
                                created_by=employee.id, terminal_id=terminal.id)
    db.session.add(binding)
    db.session.flush()
    if old:
        old.replaced_by_id = binding.id
    data = {'member': member_dict(member), 'card_binding': member_card_binding_dict(binding)}
    write_audit('member.card_replace' if old else 'member.card_bind', 'member', member.id,
        {'old_card_binding_id': old.id if old else None, **data},
        employee_id=employee.id, terminal_id=terminal.id)
    return _capture(endpoint, employee, key, data, 200)
