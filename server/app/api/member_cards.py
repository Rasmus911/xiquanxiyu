"""Authenticated physical membership identification and paid card writes."""
import logging
from datetime import date

from flask import Blueprint, request
from flask_jwt_extended import get_jwt

from ..access_policy import emit_business_event
from ..auth_service import current_employee, require_permission
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..idempotency_service import idempotency_lookup
from ..member_card_models import MemberCardBinding
from ..member_cards import (bind_physical_card, card_uid_value, member_pass_dict,
                            normalize_phone, open_physical_member, physical_request_key)
from ..models import Member, MemberPass, Terminal
from ..serializers import member_dict
from ..sms_service import notify_card_opened
from .errors import ApiError, success
from .members import _record_sms_notifications

bp = Blueprint('member_cards', __name__, url_prefix='/members')
logger = logging.getLogger(__name__)


def _body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError('请求内容需要是对象')
    return payload


def _terminal():
    return db.session.get(Terminal, get_jwt()['terminal_id'])


@bp.post('/physical-open')
@require_permission('member:write')
@serialized_financial_write
def physical_open():
    employee = current_employee()
    payload = _body()
    replay = idempotency_lookup('members:physical-open', employee.id, physical_request_key(payload))
    data = open_physical_member(employee, _terminal(), payload)
    db.session.commit()
    if not replay:
        # Delivery is after durable collection and never part of its retry result.
        try:
            emit_business_event('member.changed', {'member_id': data['member']['id']})
        except Exception:
            logger.exception('Failed to emit physical member opening event')
        try:
            member = db.session.get(Member, data['member']['id'])
            details = ({'balance': data['member']['balance']} if payload['membership_type'] == 'stored'
                       else {'remaining': data['member_pass']['remaining_count'],
                             'total': data['member_pass']['remaining_count']})
            notifications = notify_card_opened(member, employee, payload['membership_type'], **details)
            _record_sms_notifications(member, payload['membership_type'], notifications)
        except Exception:
            db.session.rollback()
            logger.exception('Failed to notify physical member opening')
    return success(data, '已返回原开卡结果' if replay else '实体卡开通成功', 200 if replay else 201)


@bp.post('/<member_id>/physical-card')
@require_permission('member:write')
@serialized_financial_write
def physical_card(member_id):
    employee = current_employee()
    payload = _body()
    member = Member.query.filter_by(id=member_id).first()
    if not member:
        raise ApiError('会员不存在', 404, 'MEMBER_NOT_FOUND')
    replay = idempotency_lookup(f'members:{member_id}:physical-card', employee.id, physical_request_key(payload))
    data = bind_physical_card(member, employee, _terminal(), payload)
    db.session.commit()
    if not replay:
        try:
            emit_business_event('member.changed', {'member_id': member_id})
        except Exception:
            logger.exception('Failed to emit member card binding event')
    return success(data, '实体卡绑定成功')


@bp.get('/lookup')
@require_permission('member:read')
def lookup_member():
    has_phone, has_card = 'phone' in request.args, 'card_uid' in request.args
    if has_phone == has_card or any(len(request.args.getlist(key)) != 1
                                    for key in ('phone', 'card_uid') if key in request.args):
        raise ApiError('请提供手机号或实体卡号其中一项', code='INVALID_LOOKUP')
    if has_card:
        uid = card_uid_value(request.args['card_uid'])
        binding = MemberCardBinding.query.filter_by(card_uid=uid).first()
        if not binding:
            raise ApiError('未找到该实体卡', 404, 'CARD_NOT_FOUND')
        if not binding.is_active:
            raise ApiError('该实体卡已作废，请使用新卡', 409, 'CARD_REVOKED')
        member = Member.query.filter_by(id=binding.member_id, is_active=True).filter(
            Member.deleted_at.is_(None)).first()
    else:
        phone = normalize_phone(request.args['phone'])
        member = Member.query.filter_by(phone=phone, is_active=True).filter(Member.deleted_at.is_(None)).first()
    if not member:
        raise ApiError('未找到对应的有效会员', 404, 'MEMBER_NOT_FOUND')
    passes = MemberPass.query.filter(MemberPass.member_id == member.id, MemberPass.is_active.is_(True),
        MemberPass.remaining_count > 0, db.or_(MemberPass.valid_until.is_(None), MemberPass.valid_until >= date.today()))
    return success({**member_dict(member), 'passes': [member_pass_dict(row) for row in passes.order_by(MemberPass.created_at).all()]})
