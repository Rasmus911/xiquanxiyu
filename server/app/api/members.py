import logging
import re
from datetime import date
from decimal import Decimal

from flask import Blueprint, request

from ..access_policy import emit_business_event
from ..audit_service import write_audit
from ..auth_service import current_employee, require_permission, verify_sensitive_password
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..idempotency_service import (
    financial_request_key,
    guard_financial_request,
    idempotency_lookup,
    idempotency_record_key,
    idempotency_store,
)
from ..models import Member, MemberPass, PassLedger, StoredValueLedger, Visit, utcnow
from ..serializers import decimal_str, iso, member_dict
from ..sms_service import notify_card_opened
from ..validation import decimal_value
from .errors import ApiError, success

bp = Blueprint("members", __name__, url_prefix="/members")
logger = logging.getLogger(__name__)


def normalize_phone(value):
    phone = re.sub(r"\D", "", str(value or ""))
    if len(phone) != 11:
        raise ApiError("请输入 11 位手机号")
    return phone


def _money(value):
    return decimal_value(value, "金额", positive=True)


def pass_dict(row):
    return {
        "id": row.id,
        "name": row.name,
        "remaining_count": row.remaining_count,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "is_active": row.is_active,
    }


def _record_sms_notifications(member, card_type, notifications):
    try:
        for notification in notifications:
            write_audit(
                "member.card_sms",
                "member",
                member.id,
                {
                    "card_type": card_type,
                    "recipient": notification.get("recipient"),
                    "success": notification.get("success"),
                    "status": notification.get("status"),
                    "message": notification.get("message"),
                    "provider_code": notification.get("provider_code"),
                    "request_id": notification.get("request_id"),
                },
            )
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to save member card SMS audit member_id=%s", member.id)


@bp.get("")
@require_permission("member:read")
def list_members():
    keyword = request.args.get("keyword", "").strip()
    query = Member.query.filter(Member.deleted_at.is_(None))
    if keyword:
        digits = re.sub(r"\D", "", keyword)
        query = query.filter(db.or_(Member.phone.ilike(f"%{digits}%"), Member.name.ilike(f"%{keyword}%")))
    rows = query.order_by(Member.created_at.desc()).limit(200).all()
    member_ids = [row.id for row in rows]
    passes = (
        MemberPass.query.filter(
            MemberPass.member_id.in_(member_ids),
            MemberPass.is_active.is_(True),
            MemberPass.remaining_count > 0,
        ).all()
        if member_ids
        else []
    )
    pass_summary = {}
    for member_pass in passes:
        if member_pass.valid_until and member_pass.valid_until < date.today():
            continue
        bucket = pass_summary.setdefault(member_pass.member_id, {"count": 0, "remaining": 0})
        bucket["count"] += 1
        bucket["remaining"] += member_pass.remaining_count
    return success(
        [
            {
                **member_dict(row),
                "has_stored_value": Decimal(row.balance) > 0,
                "has_pass": row.id in pass_summary,
                "active_pass_count": pass_summary.get(row.id, {}).get("count", 0),
                "pass_remaining": pass_summary.get(row.id, {}).get("remaining", 0),
            }
            for row in rows
        ]
    )


@bp.get("/lookup")
@require_permission("member:read")
def lookup_member():
    phone = normalize_phone(request.args.get("phone"))
    member = Member.query.filter_by(phone=phone, is_active=True).first()
    if not member:
        raise ApiError("未找到该手机号对应的有效会员", 404, "MEMBER_NOT_FOUND")
    return success(member_dict(member))


@bp.post("")
@require_permission("member:write")
@serialized_financial_write
def create_member():
    body = request.get_json(silent=True) or {}
    phone = normalize_phone(body.get("phone"))
    if Member.query.filter_by(phone=phone).first():
        raise ApiError("手机号已经注册", 409, "PHONE_EXISTS")
    member = Member(
        phone=phone,
        name=str(body.get("name", "")).strip() or None,
        note=str(body.get("note", "")).strip() or None,
    )
    db.session.add(member)
    db.session.flush()
    write_audit("member.create", "member", member.id, member_dict(member))
    db.session.commit()
    return success(member_dict(member), "会员创建成功", 201)


@bp.get("/<member_id>")
@require_permission("member:read")
def get_member(member_id):
    member = db.session.get(Member, member_id)
    if not member or member.deleted_at:
        raise ApiError("会员不存在", 404, "NOT_FOUND")
    ledgers = (
        StoredValueLedger.query.filter_by(member_id=member.id)
        .order_by(StoredValueLedger.created_at.desc())
        .limit(100)
        .all()
    )
    passes = MemberPass.query.filter_by(member_id=member.id).order_by(MemberPass.created_at.desc()).all()
    return success(
        {
            **member_dict(member),
            "ledgers": [
                {
                    "id": row.id,
                    "entry_type": row.entry_type,
                    "amount": decimal_str(row.amount),
                    "balance_after": decimal_str(row.balance_after),
                    "payment_method": row.payment_method,
                    "note": row.note,
                    "created_at": iso(row.created_at),
                }
                for row in ledgers
            ],
            "passes": [pass_dict(row) for row in passes],
        }
    )


@bp.delete("/<member_id>")
@require_permission("member:delete")
@serialized_financial_write
def delete_member(member_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    verify_sensitive_password(employee, body.get('password'))
    member = Member.query.filter_by(id=member_id).with_for_update().first()
    if not member:
        raise ApiError('会员不存在', 404, 'NOT_FOUND')
    if member.deleted_at:
        db.session.commit()
        return success(member_dict(member), '会员已归档')
    if (Decimal(member.balance) != 0
            or MemberPass.query.filter(MemberPass.member_id == member.id, MemberPass.remaining_count > 0).first()
            or Visit.query.filter(Visit.member_id == member.id, Visit.status.in_(['open', 'settling'])).first()):
        raise ApiError('会员仍有余额、次卡权益或未完成业务，请先处理', 409, 'MEMBER_DELETE_BLOCKED')
    before = member_dict(member)
    member.deleted_at = utcnow()
    member.is_active = False
    member.version += 1
    write_audit('member.delete', 'member', member.id,
        {'before': before, 'after': {**member_dict(member), 'deleted_at': iso(member.deleted_at)}})
    db.session.commit()
    emit_business_event('member.changed', {'member_id': member.id})
    return success(member_dict(member), '会员已归档')


@bp.post("/<member_id>/recharge")
@require_permission("member:write")
@serialized_financial_write
def recharge(member_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    if not key:
        raise ApiError("缺少幂等请求编号")
    key = financial_request_key(f'members:{member_id}:recharge', employee.id, key)
    existing = StoredValueLedger.query.filter_by(idempotency_key=key).first()
    guard_financial_request(
        f"members:{member_id}:recharge", employee, key, body, existing, existing.operator_id if existing else None
    )
    if existing:
        if existing.member_id != member_id or existing.amount != _money(body.get("amount")):
            raise ApiError("重复请求的会员或金额不一致", 409, "IDEMPOTENCY_CONFLICT")
        member = db.session.get(Member, member_id)
        return success(member_dict(member), "已返回原充值结果")
    member = Member.query.with_for_update().filter_by(id=member_id, is_active=True).first()
    if not member:
        raise ApiError("会员不存在或已停用", 404, "NOT_FOUND")
    has_stored_card = StoredValueLedger.query.filter_by(member_id=member.id, entry_type="recharge").first() is not None
    amount = _money(body.get("amount"))
    payment_method = str(body.get("payment_method", ""))
    if payment_method not in {"cash", "wechat", "alipay"}:
        raise ApiError("充值支付方式无效")
    before_balance = Decimal(member.balance)
    member.balance = decimal_value(before_balance + amount, "充值后余额")
    member.version += 1
    ledger = StoredValueLedger(
        member_id=member.id,
        amount=amount,
        balance_after=member.balance,
        entry_type="recharge",
        payment_method=payment_method,
        shift_id=None,
        operator_id=employee.id,
        note=str(body.get("note", "")).strip() or None,
        idempotency_key=key,
    )
    db.session.add(ledger)
    write_audit(
        "member.recharge",
        "member",
        member.id,
        {
            "amount": str(amount),
            "payment_method": payment_method,
            "balance_after": str(member.balance),
            "balance_before": str(before_balance),
        },
    )
    db.session.commit()
    emit_business_event("member.changed", {"member_id": member.id})
    payload = member_dict(member)
    if not has_stored_card:
        notifications = notify_card_opened(
            member,
            employee,
            "stored",
            balance=decimal_str(member.balance),
        )
        _record_sms_notifications(member, "stored", notifications)
        payload["sms_notifications"] = notifications
    return success(payload, "充值成功")


@bp.post("/<member_id>/passes")
@require_permission("member:write")
@serialized_financial_write
def issue_pass(member_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    key = str(request.headers.get("Idempotency-Key") or body.get("idempotency_key") or "").strip()
    if not key:
        raise ApiError("缺少幂等请求编号", 400, "IDEMPOTENCY_REQUIRED")
    key = financial_request_key(f'members:{member_id}:passes', employee.id, key)
    existing = PassLedger.query.filter_by(idempotency_key=key, entry_type="issue").first()
    guard_financial_request(
        f"members:{member_id}:passes", employee, key, body, existing, existing.operator_id if existing else None
    )
    if existing:
        member_pass = db.session.get(MemberPass, existing.member_pass_id)
        if member_pass.member_id != member_id:
            raise ApiError("重复请求的会员不一致", 409, "IDEMPOTENCY_CONFLICT")
        return success(pass_dict(member_pass), "已返回原次卡开通结果")
    member = Member.query.with_for_update().filter_by(id=member_id, is_active=True).first()
    if not member or not member.is_active:
        raise ApiError("会员不存在或已停用", 404, "NOT_FOUND")
    from ..validation import integer_value

    count = integer_value(body.get("count", 0), "次卡次数")
    amount = _money(body.get("amount"))
    payment_method = str(body.get("payment_method", "")).strip()
    if payment_method not in {"cash", "wechat", "alipay"}:
        raise ApiError("次卡支付方式无效")
    try:
        valid_until = date.fromisoformat(body["valid_until"]) if body.get("valid_until") else None
    except (TypeError, ValueError):
        raise ApiError("次卡有效期需要是正确的 YYYY-MM-DD 日期", code="INVALID_DATE") from None
    member_pass = MemberPass(
        member_id=member.id,
        name=str(body.get("name", "洗浴次卡")).strip() or "洗浴次卡",
        remaining_count=count,
        valid_until=valid_until,
    )
    db.session.add(member_pass)
    db.session.flush()
    db.session.add(
        PassLedger(
            member_pass_id=member_pass.id,
            delta=count,
            balance_after=count,
            entry_type="issue",
            amount_paid=amount,
            payment_method=payment_method,
            idempotency_key=key,
            operator_id=employee.id,
            note=str(body.get("note", "")).strip() or None,
        )
    )
    write_audit(
        "member.pass_issue",
        "member_pass",
        member_pass.id,
        {**pass_dict(member_pass), "amount": str(amount), "payment_method": payment_method},
    )
    db.session.commit()
    emit_business_event("member.changed", {"member_id": member.id})
    notifications = notify_card_opened(
        member,
        employee,
        "pass",
        remaining=count,
        total=count,
    )
    _record_sms_notifications(member, "pass", notifications)
    return success(
        {**pass_dict(member_pass), "sms_notifications": notifications},
        "次卡发放成功",
        201,
    )


@bp.post("/passes/<pass_id>/consume")
@require_permission("member:write")
@serialized_financial_write
def consume_pass(pass_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    key = str(request.headers.get("Idempotency-Key") or body.get("idempotency_key") or "").strip()
    if not key:
        raise ApiError("缺少幂等请求编号", 400, "IDEMPOTENCY_REQUIRED")
    endpoint = f"passes:{pass_id}:consume"
    existing = idempotency_lookup(endpoint, employee.id, key)
    if existing:
        return success(existing.response_body["data"], "已返回原核销结果")
    member_pass = MemberPass.query.with_for_update().filter_by(id=pass_id).first()
    if not member_pass or not member_pass.is_active:
        raise ApiError("次卡不存在或已停用", 404, "NOT_FOUND")
    if member_pass.valid_until and member_pass.valid_until < date.today():
        raise ApiError("次卡已经过期", 409, "PASS_EXPIRED")
    if member_pass.remaining_count <= 0:
        raise ApiError("次卡次数不足", 409, "PASS_EMPTY")
    member_pass.remaining_count -= 1
    member_pass.version += 1
    db.session.add(
        PassLedger(
            member_pass_id=member_pass.id,
            delta=-1,
            balance_after=member_pass.remaining_count,
            entry_type="consume",
            operator_id=employee.id,
            note=str(body.get("note", "")).strip() or None,
        )
    )
    write_audit(
        "member.pass_consume",
        "member_pass",
        member_pass.id,
        {"remaining_before": member_pass.remaining_count + 1, "remaining_count": member_pass.remaining_count},
    )
    payload = pass_dict(member_pass)
    idempotency_store(idempotency_record_key(endpoint, employee.id, key), endpoint, 200, {"data": payload})
    db.session.commit()
    return success(payload, "次卡核销成功")
