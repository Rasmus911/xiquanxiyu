from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, request

from ..auth_service import require_permission
from ..models import OrderItem, PassLedger, Payment, Settlement, SettlementVisit, StoredValueLedger, Visit
from ..serializers import decimal_str
from .errors import ApiError, success

bp = Blueprint("reports", __name__, url_prefix="/reports")
BUSINESS_TZ = timezone(timedelta(hours=8))


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _local(value):
    return _utc(value).astimezone(BUSINESS_TZ)


def _range():
    try:
        start_date = _utc(datetime.fromisoformat(request.args.get("start")))
        end_date = _utc(datetime.fromisoformat(request.args.get("end")))
    except (TypeError, ValueError):
        today = datetime.now(BUSINESS_TZ).date()
        start_date = datetime.combine(today, time.min, BUSINESS_TZ).astimezone(timezone.utc)
        end_date = start_date + timedelta(days=1)
    if end_date <= start_date:
        raise ApiError("结束时间必须晚于开始时间")
    if end_date - start_date > timedelta(days=366):
        raise ApiError('报表查询范围不能超过366天')
    return start_date, end_date


@bp.get("/summary")
@require_permission("report:read")
def summary():
    start, end = _range()
    return success(summary_data(start, end))


def summary_data(start, end):
    settlements = Settlement.query.filter(
        Settlement.completed_at >= start,
        Settlement.completed_at < end,
    ).all()
    gross_sales = sum((Decimal(row.total_amount) for row in settlements), Decimal("0.00"))
    payments = Payment.query.filter(Payment.created_at >= start, Payment.created_at < end).all()
    payment_totals = {}
    for row in payments:
        payment_totals[row.method] = payment_totals.get(row.method, Decimal("0.00")) + Decimal(row.amount)
    refund_total = -sum(
        (Decimal(row.amount) for row in payments if row.kind == "refund"),
        Decimal("0.00"),
    )
    operating_revenue = gross_sales - refund_total
    recharges = StoredValueLedger.query.filter(
        StoredValueLedger.created_at >= start,
        StoredValueLedger.created_at < end,
        StoredValueLedger.entry_type == "recharge",
    ).all()
    stored_value_recharge = sum((Decimal(row.amount) for row in recharges), Decimal("0.00"))
    recharge_payment_totals = {}
    for row in recharges:
        method = row.payment_method or "other"
        recharge_payment_totals[method] = recharge_payment_totals.get(method, Decimal("0.00")) + Decimal(row.amount)

    pass_sales = PassLedger.query.filter(
        PassLedger.created_at >= start,
        PassLedger.created_at < end,
        PassLedger.entry_type == "issue",
        PassLedger.amount_paid > 0,
    ).all()
    pass_card_sales = sum((Decimal(row.amount_paid) for row in pass_sales), Decimal("0.00"))
    pass_payment_totals = {}
    for row in pass_sales:
        method = row.payment_method or "other"
        pass_payment_totals[method] = pass_payment_totals.get(method, Decimal("0.00")) + Decimal(row.amount_paid)
    member_recharge = stored_value_recharge + pass_card_sales

    cashflow_totals = {method: amount for method, amount in payment_totals.items() if method != "balance" and amount}
    for method, amount in recharge_payment_totals.items():
        cashflow_totals[method] = cashflow_totals.get(method, Decimal("0.00")) + amount
    for method, amount in pass_payment_totals.items():
        cashflow_totals[method] = cashflow_totals.get(method, Decimal("0.00")) + amount
    stored_value_consumed = payment_totals.get("balance", Decimal("0.00"))
    actual_cash_inflow = sum(cashflow_totals.values(), Decimal("0.00"))
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "settlement_count": len(settlements),
        "gross_sales": decimal_str(gross_sales),
        "refund_total": decimal_str(refund_total),
        "operating_revenue": decimal_str(operating_revenue),
        "payment_totals": {key: decimal_str(value) for key, value in payment_totals.items()},
        "stored_value_recharge": decimal_str(stored_value_recharge),
        "pass_card_sales": decimal_str(pass_card_sales),
        "member_recharge": decimal_str(member_recharge),
        "recharge_payment_totals": {key: decimal_str(value) for key, value in recharge_payment_totals.items()},
        "pass_payment_totals": {key: decimal_str(value) for key, value in pass_payment_totals.items()},
        "stored_value_consumed": decimal_str(stored_value_consumed),
        "cashflow_totals": {key: decimal_str(value) for key, value in cashflow_totals.items()},
        "actual_cash_inflow": decimal_str(actual_cash_inflow),
        "cash_inflow": decimal_str(actual_cash_inflow),
    }


@bp.get("/items")
@require_permission("report:read")
def item_report():
    start, end = _range()
    return success(item_report_data(start, end))


def item_report_data(start, end):
    rows = (
        OrderItem.query.join(Visit, OrderItem.visit_id == Visit.id)
        .join(SettlementVisit, SettlementVisit.visit_id == Visit.id)
        .join(Settlement, Settlement.id == SettlementVisit.settlement_id)
        .filter(
            Settlement.completed_at >= start,
            Settlement.completed_at < end,
            Settlement.status == "completed",
            OrderItem.status == "active",
        )
        .all()
    )
    totals = {}
    for row in rows:
        key = f"{row.kind}:{row.name_snapshot}"
        bucket = totals.setdefault(
            key,
            {
                "kind": row.kind,
                "name": row.name_snapshot,
                "quantity": Decimal("0"),
                "amount": Decimal("0"),
            },
        )
        bucket["quantity"] += Decimal(row.quantity)
        bucket["amount"] += Decimal(row.total_amount)
    return [
        {**value, "quantity": str(value["quantity"]), "amount": decimal_str(value["amount"])}
        for value in totals.values()
    ]


@bp.get("/trend")
@require_permission("report:read")
def daily_trend():
    start, end = _range()
    return success(trend_data(start, end))


def trend_data(start, end):
    if end - start > timedelta(days=92):
        raise ApiError("趋势图查询范围不能超过 92 天")

    days = {}
    cursor = _local(start).date()
    while datetime.combine(cursor, time.min, BUSINESS_TZ) < _utc(end):
        days[cursor.isoformat()] = {
            "date": cursor.isoformat(),
            "revenue": Decimal("0.00"),
            "recharge": Decimal("0.00"),
            "cash_inflow": Decimal("0.00"),
            "settlement_count": 0,
        }
        cursor += timedelta(days=1)

    settlements = Settlement.query.filter(
        Settlement.completed_at >= start,
        Settlement.completed_at < end,
    ).all()
    for settlement in settlements:
        bucket = days.get(_local(settlement.completed_at).date().isoformat())
        if not bucket:
            continue
        bucket["settlement_count"] += 1
        bucket["revenue"] += Decimal(settlement.total_amount)

    payments = Payment.query.filter(Payment.created_at >= start, Payment.created_at < end).all()
    for payment in payments:
        bucket = days.get(_local(payment.created_at).date().isoformat())
        if not bucket:
            continue
        if payment.kind == "refund":
            bucket["revenue"] += Decimal(payment.amount)
        if payment.method != "balance":
            bucket["cash_inflow"] += Decimal(payment.amount)

    recharges = StoredValueLedger.query.filter(
        StoredValueLedger.created_at >= start,
        StoredValueLedger.created_at < end,
        StoredValueLedger.entry_type == "recharge",
    ).all()
    for recharge in recharges:
        bucket = days.get(_local(recharge.created_at).date().isoformat())
        if bucket:
            bucket["recharge"] += Decimal(recharge.amount)
            bucket["cash_inflow"] += Decimal(recharge.amount)

    pass_sales = PassLedger.query.filter(
        PassLedger.created_at >= start,
        PassLedger.created_at < end,
        PassLedger.entry_type == "issue",
        PassLedger.amount_paid > 0,
    ).all()
    for sale in pass_sales:
        bucket = days.get(_local(sale.created_at).date().isoformat())
        if bucket:
            bucket["recharge"] += Decimal(sale.amount_paid)
            bucket["cash_inflow"] += Decimal(sale.amount_paid)

    return [
        {
            **bucket,
            "revenue": decimal_str(bucket["revenue"]),
            "recharge": decimal_str(bucket["recharge"]),
            "cash_inflow": decimal_str(bucket["cash_inflow"]),
        }
        for bucket in days.values()
    ]


@bp.get('/insights')
@require_permission('report:read')
def insights():
    start, end = _range()
    return success(insights_data(start, end))


def insights_data(start, end):
    """Settled wristband visits are the denominator, never merged bill count."""
    from ..models import StockMovement
    from ..stock_cost_service import current_cost
    current = summary_data(start, end)
    previous = summary_data(start - (end - start), start)
    rows = db_visit_rows(start, end)
    hours = [{'hour':hour, 'visits':0, 'gross_amount':Decimal(0)} for hour in range(24)]
    member_visits = 0
    for visit, link, settlement in rows:
        bucket = hours[_local(visit.opened_at).hour]
        bucket['visits'] += 1
        bucket['gross_amount'] += Decimal(link.amount)
        member_visits += int(bool(visit.member_id or settlement.member_id))
    receipts = StockMovement.query.filter(StockMovement.movement_type=='purchase',
        StockMovement.created_at>=start, StockMovement.created_at<end).all()
    amount, unpriced = Decimal(0), 0
    for receipt in receipts:
        cost = current_cost(receipt.id)
        if cost is None:
            unpriced += 1
        else:
            amount += cost.total_cost
    count = len(rows)
    return {'current':current, 'previous':previous, 'visit_count':count,
        'average_visit_revenue':decimal_str(Decimal(current['operating_revenue']) / count) if count else None,
        'member_visit_count':member_visits, 'nonmember_visit_count':count-member_visits,
        'member_visit_share':round(member_visits / count * 100, 1) if count else None,
        'hours':[{**row, 'gross_amount':decimal_str(row['gross_amount'])} for row in hours],
        'purchase_cost':{'recorded_amount':decimal_str(amount), 'unpriced_receipts':unpriced,
                         'receipt_count':len(receipts)},
        'definitions':{'visits':'期间结账的手牌人次，合并结账仍按每个手牌计算',
            'hours':'期间已结账手牌的入场时段，北京时间；非期间全部到店客流',
            'member_share':'会员关联或会员结算账单的人次占比，不等于可识别顾客复购率',
            'cost':'期间采购入库金额（只计最新成本记录），不是已消耗成本，不扣除计算利润'}}


def db_visit_rows(start, end):
    from ..extensions import db
    return db.session.query(Visit, SettlementVisit, Settlement).join(
        SettlementVisit, SettlementVisit.visit_id==Visit.id).join(
        Settlement, Settlement.id==SettlementVisit.settlement_id).filter(
        Settlement.completed_at>=start, Settlement.completed_at<end).all()
