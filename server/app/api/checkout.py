import secrets
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, request
from flask_jwt_extended import get_jwt

from ..access_policy import emit_business_event
from ..audit_service import write_audit
from ..auth_service import current_employee, require_permission, verify_sensitive_password
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..idempotency_service import financial_request_key, guard_financial_request
from ..models import (
    Member,
    OrderItem,
    Payment,
    PrintJob,
    Settlement,
    SettlementVisit,
    StoredValueLedger,
    SystemSetting,
    Visit,
    Wristband,
    utcnow,
)
from ..serializers import decimal_str, payment_dict, settlement_dict
from ..validation import decimal_value
from .errors import ApiError, success

bp = Blueprint("checkout", __name__, url_prefix="/checkout")
PAYMENT_METHODS = {"cash", "wechat", "alipay", "balance"}
CHECKOUT_SCOPES = {"party", "selected"}


def _money(value):
    return decimal_value(value, "支付金额", positive=True)


def _receipt_number():
    return f"XS{datetime.now():%Y%m%d%H%M%S}{secrets.token_hex(2).upper()}"


def _visit_total(visit_id):
    rows = OrderItem.query.filter_by(visit_id=visit_id, status="active").all()
    total = sum((Decimal(row.total_amount) for row in rows), Decimal("0.00"))
    return total.quantize(Decimal("0.01")), rows


def _checkout_scope(body):
    scope = str(body.get("checkout_scope", "party")).strip().lower()
    if scope not in CHECKOUT_SCOPES:
        raise ApiError("结账范围无效")
    return scope


def _expand_open_visits(requested_visit_ids, lock=False, include_linked=True):
    requested_visit_ids = sorted(set(requested_visit_ids))
    query = Visit.query.filter(Visit.id.in_(requested_visit_ids), Visit.status == "open")
    if lock:
        query = query.with_for_update()
    requested_visits = query.all()
    if len(requested_visits) != len(requested_visit_ids):
        raise ApiError("部分账单已变化，请刷新", 409, "VISIT_CHANGED")
    party_ids = {row.party_id for row in requested_visits if row.party_id}
    visits = list(requested_visits)
    if party_ids:
        party_query = Visit.query.filter(Visit.party_id.in_(party_ids), Visit.status == "open")
        if lock:
            party_query = party_query.with_for_update()
        party_visits = party_query.all()
        if include_linked:
            visits.extend(party_visits)
    return sorted({row.id: row for row in visits}.values(), key=lambda row: row.id)


def _load_settlement_payload(settlement):
    payments = Payment.query.filter_by(settlement_id=settlement.id).order_by(Payment.created_at).all()
    links = SettlementVisit.query.filter_by(settlement_id=settlement.id).all()
    visits = []
    for link in links:
        visit = db.session.get(Visit, link.visit_id)
        wristband = db.session.get(Wristband, visit.wristband_id) if visit else None
        visits.append(
            {
                "visit_id": link.visit_id,
                "wristband_number": wristband.number if wristband else None,
                "amount": decimal_str(link.amount),
            }
        )
    return settlement_dict(settlement, payments, visits)


@bp.post("/preview")
@require_permission("checkout:write")
@serialized_financial_write
def preview():
    body = request.get_json(silent=True) or {}
    checkout_scope = _checkout_scope(body)
    requested_visit_ids = sorted(set(body.get("visit_ids") or []))
    if not requested_visit_ids:
        raise ApiError("请选择至少一个手牌")
    visits = _expand_open_visits(
        requested_visit_ids,
        include_linked=checkout_scope == "party",
    )
    details = []
    total = Decimal("0.00")
    for visit in visits:
        visit_total, _ = _visit_total(visit.id)
        wristband = db.session.get(Wristband, visit.wristband_id)
        total += visit_total
        details.append(
            {
                "visit_id": visit.id,
                "wristband_number": wristband.number,
                "amount": decimal_str(visit_total),
                "version": visit.version,
                "party_id": visit.party_id,
            }
        )
    return success(
        {
            "visits": details,
            "total_amount": decimal_str(total),
            "auto_included_linked_visits": len(visits) - len(requested_visit_ids),
            "checkout_scope": checkout_scope,
        }
    )


@bp.post("")
@require_permission("checkout:write")
@serialized_financial_write
def complete_checkout():
    employee = current_employee()
    claims = get_jwt()
    terminal_id = claims.get("terminal_id")
    body = request.get_json(silent=True) or {}
    checkout_scope = _checkout_scope(body)
    idempotency_key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    if not idempotency_key:
        raise ApiError("缺少幂等请求编号", code="IDEMPOTENCY_REQUIRED")
    idempotency_key = financial_request_key('checkout', employee.id, idempotency_key)
    existing = Settlement.query.filter_by(idempotency_key=idempotency_key).first()
    guard_financial_request(
        "checkout", employee, idempotency_key, body, existing, existing.created_by_id if existing else None
    )
    if existing:
        return success(_load_settlement_payload(existing), "已返回原结账结果")

    requested_visit_ids = sorted(set(body.get("visit_ids") or []))
    if not requested_visit_ids:
        raise ApiError("请选择至少一个手牌")
    visits = _expand_open_visits(
        requested_visit_ids,
        lock=True,
        include_linked=checkout_scope == "party",
    )
    visit_ids = [row.id for row in visits]
    affected_party_ids = {row.party_id for row in visits if row.party_id}

    shift = None

    totals = []
    total_amount = Decimal("0.00")
    for visit in visits:
        amount, _items = _visit_total(visit.id)
        totals.append((visit, amount))
        total_amount += amount
    total_amount = decimal_value(total_amount, '应收合计')

    payment_rows = body.get("payments") or []
    if not isinstance(payment_rows, list) or any(not isinstance(row, dict) for row in payment_rows):
        raise ApiError("支付明细格式无效", code="INVALID_PAYMENTS")
    normalized_payments = []
    paid_amount = Decimal("0.00")
    for payment in payment_rows:
        method = str(payment.get("method", ""))
        if method not in PAYMENT_METHODS:
            raise ApiError("支付方式无效")
        amount = _money(payment.get("amount"))
        normalized_payments.append((method, amount, str(payment.get("reference", "")).strip()))
        paid_amount += amount
    if paid_amount.quantize(Decimal("0.01")) != total_amount:
        raise ApiError(
            "支付金额必须等于应收金额",
            details={"expected": decimal_str(total_amount), "actual": decimal_str(paid_amount)},
        )

    member = None
    balance_amount = sum(
        (amount for method, amount, _ref in normalized_payments if method == "balance"),
        Decimal("0.00"),
    )
    if balance_amount:
        member_id = body.get("member_id") or next((row.member_id for row in visits if row.member_id), None)
        member = Member.query.with_for_update().filter_by(id=member_id, is_active=True).first()
        if not member:
            raise ApiError("使用储值支付时必须选择有效会员")
        if Decimal(member.balance) < balance_amount:
            raise ApiError("会员储值余额不足", 409, "INSUFFICIENT_BALANCE")

    settlement = Settlement(
        number=_receipt_number(),
        total_amount=total_amount,
        paid_amount=paid_amount,
        created_by_id=employee.id,
        terminal_id=terminal_id,
        shift_id=shift.id if shift else None,
        member_id=member.id if member else None,
        idempotency_key=str(idempotency_key),
    )
    db.session.add(settlement)
    db.session.flush()

    for visit, amount in totals:
        db.session.add(SettlementVisit(settlement_id=settlement.id, visit_id=visit.id, amount=amount))
        visit.status = "closed"
        visit.closed_at = utcnow()
        visit.party_id = None
        visit.version += 1
        wristband = Wristband.query.with_for_update().filter_by(id=visit.wristband_id).first()
        if wristband.status == "in_use":
            wristband.status = "available"
            wristband.version += 1

    if affected_party_ids:
        remaining_visits = (
            Visit.query.with_for_update().filter(Visit.party_id.in_(affected_party_ids), Visit.status == "open").all()
        )
        remaining_by_party = {}
        for remaining_visit in remaining_visits:
            remaining_by_party.setdefault(remaining_visit.party_id, []).append(remaining_visit)
        for party_visits in remaining_by_party.values():
            if len(party_visits) == 1:
                party_visits[0].party_id = None
                party_visits[0].version += 1

    payments = []
    for method, amount, reference in normalized_payments:
        payment = Payment(
            settlement_id=settlement.id,
            shift_id=shift.id if shift else None,
            method=method,
            amount=amount,
            reference=reference or None,
        )
        payments.append(payment)
        db.session.add(payment)

    if member and balance_amount:
        member.balance = Decimal(member.balance) - balance_amount
        member.version += 1
        db.session.add(
            StoredValueLedger(
                member_id=member.id,
                amount=-balance_amount,
                balance_after=member.balance,
                entry_type="consume",
                settlement_id=settlement.id,
                operator_id=employee.id,
                note=f"结算单 {settlement.number}",
            )
        )

    print_job = PrintJob(settlement_id=settlement.id, terminal_id=terminal_id)
    db.session.add(print_job)
    write_audit(
        "checkout.complete",
        "settlement",
        settlement.id,
        {
            "number": settlement.number,
            "visit_ids": visit_ids,
            "checkout_scope": checkout_scope,
            "total_amount": str(total_amount),
            "payments": [
                {"method": method, "amount": str(amount), "reference": reference}
                for method, amount, reference in normalized_payments
            ],
        },
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"reason": "checkout"})
    emit_business_event("checkout.completed", {"settlement_id": settlement.id})
    return success(_load_settlement_payload(settlement), "结账成功", 201)


@bp.get("/<settlement_id>/receipt")
@require_permission("checkout:write")
def receipt(settlement_id):
    settlement = db.session.get(Settlement, settlement_id)
    if not settlement:
        raise ApiError("结算单不存在", 404, "NOT_FOUND")
    links = SettlementVisit.query.filter_by(settlement_id=settlement.id).all()
    visit_rows = []
    for link in links:
        visit = db.session.get(Visit, link.visit_id)
        wristband = db.session.get(Wristband, visit.wristband_id)
        items = OrderItem.query.filter_by(visit_id=visit.id, status="active").all()
        visit_rows.append(
            {
                "wristband_number": wristband.number,
                "amount": decimal_str(link.amount),
                "items": [
                    {
                        "name": item.name_snapshot,
                        "quantity": str(item.quantity),
                        "unit_price": decimal_str(item.unit_price),
                        "covered_quantity": str(item.covered_quantity or 0),
                        "included_amount": decimal_str(Decimal(item.unit_price)*Decimal(item.covered_quantity or 0)),
                        "total_amount": decimal_str(item.total_amount),
                    }
                    for item in items
                ],
            }
        )
    setting = SystemSetting.query.filter_by(key="store_name").first()
    payments = Payment.query.filter_by(settlement_id=settlement.id).all()
    job = PrintJob.query.filter_by(settlement_id=settlement.id).first()
    return success(
        {
            "store_name": setting.value if setting else "溪泉洗浴",
            "settlement": _load_settlement_payload(settlement),
            "visits": visit_rows,
            "payments": [payment_dict(row) for row in payments],
            "print_job_id": job.id if job else None,
            "print_attempts": job.attempts if job else 0,
        }
    )


@bp.get("/print-jobs")
@require_permission("print:write")
def list_print_jobs():
    statuses = request.args.getlist("status") or ["pending", "failed"]
    jobs = PrintJob.query.filter(PrintJob.status.in_(statuses)).order_by(PrintJob.created_at.desc()).limit(100).all()
    result = []
    for job in jobs:
        settlement = db.session.get(Settlement, job.settlement_id)
        result.append(
            {
                "id": job.id,
                "settlement_id": job.settlement_id,
                "settlement_number": settlement.number if settlement else None,
                "amount": decimal_str(settlement.total_amount) if settlement else "0.00",
                "status": job.status,
                "attempts": job.attempts,
                "last_error": job.last_error,
                "created_at": job.created_at.isoformat(),
            }
        )
    return success(result)


@bp.post("/<settlement_id>/print-result")
@require_permission("print:write")
def record_print_result(settlement_id):
    job = PrintJob.query.filter_by(settlement_id=settlement_id).first()
    if not job:
        raise ApiError("打印任务不存在", 404, "NOT_FOUND")
    body = request.get_json(silent=True) or {}
    job.attempts += 1
    if body.get("success"):
        job.status = "success"
        job.printed_at = utcnow()
        job.last_error = None
    else:
        job.status = "failed"
        job.last_error = str(body.get("error", "打印失败"))[:500]
    write_audit(
        "receipt.print",
        "print_job",
        job.id,
        {"success": bool(body.get("success")), "attempt": job.attempts, "error": job.last_error},
    )
    db.session.commit()
    return success({"id": job.id, "status": job.status, "attempts": job.attempts})


@bp.post("/<settlement_id>/refund")
@require_permission("checkout:refund")
@serialized_financial_write
def refund(settlement_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    verify_sensitive_password(employee, body.get("password"))
    settlement = Settlement.query.with_for_update().filter_by(id=settlement_id).first()
    if not settlement or settlement.status != "completed":
        raise ApiError("结算单不存在或不可退款", 409, "NOT_REFUNDABLE")
    reason = str(body.get("reason", "")).strip()
    if not reason:
        raise ApiError("退款必须填写原因")
    if len(reason) > 255:
        raise ApiError("退款原因最多 255 字")
    shift = None
    originals = Payment.query.filter_by(settlement_id=settlement.id, kind="payment").all()
    member = None
    for original in originals:
        refund_payment = Payment(
            settlement_id=settlement.id,
            shift_id=shift.id if shift else None,
            method=original.method,
            amount=-Decimal(original.amount),
            reference=f"退款：{reason[:116]}",
            kind="refund",
            original_payment_id=original.id,
        )
        db.session.add(refund_payment)
        if original.method == "balance":
            member = Member.query.with_for_update().filter_by(id=settlement.member_id).first()
            member.balance = Decimal(member.balance) + Decimal(original.amount)
            member.version += 1
            db.session.add(
                StoredValueLedger(
                    member_id=member.id,
                    amount=original.amount,
                    balance_after=member.balance,
                    entry_type="refund",
                    settlement_id=settlement.id,
                    operator_id=employee.id,
                    note=reason,
                )
            )
    settlement.status = "refunded"
    settlement.version += 1
    write_audit(
        "checkout.refund",
        "settlement",
        settlement.id,
        {"number": settlement.number, "amount": str(settlement.total_amount), "reason": reason},
    )
    db.session.commit()
    emit_business_event("checkout.refunded", {"settlement_id": settlement.id})
    return success(_load_settlement_payload(settlement), "退款完成")
