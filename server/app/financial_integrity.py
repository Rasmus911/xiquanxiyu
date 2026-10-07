from decimal import Decimal

from .extensions import db
from .models import Member, MemberPass, OrderItem, PassLedger, Payment, Settlement, SettlementVisit, StoredValueLedger
from .package_billing import BillingLine, allocate_inclusions, line_net_total
from .package_service import validate_package_definition
from .api.errors import ApiError


def check_financial_integrity(period_id=None):
    """Reconcile one period. The caller must authorize any explicit archive scope."""
    if period_id is not None:
        from .business_period import archive_read

        with archive_read(period_id):
            return _check_financial_integrity()
    return _check_financial_integrity()


def _check_financial_integrity():
    """Reconcile mutable balances and settlement totals against append-only records."""
    issues = []
    issue_count = 0
    checked = 0

    def compare(kind, entity_id, actual, expected):
        nonlocal issue_count, checked
        checked += 1
        if Decimal(actual) != Decimal(expected):
            issue_count += 1
            if len(issues) < 100:
                issues.append({"kind": kind, "entity_id": entity_id, "actual": str(actual), "expected": str(expected)})

    for member, ledger_total in (
        db.session.query(Member, db.func.coalesce(db.func.sum(StoredValueLedger.amount), 0))
        .outerjoin(StoredValueLedger, StoredValueLedger.member_id == Member.id)
        .group_by(Member.id)
        .yield_per(500)
    ):
        compare("member_balance", member.id, member.balance, ledger_total)
    for member_pass, delta in (
        db.session.query(MemberPass, db.func.coalesce(db.func.sum(PassLedger.delta), 0))
        .outerjoin(PassLedger, PassLedger.member_pass_id == MemberPass.id)
        .group_by(MemberPass.id)
        .yield_per(500)
    ):
        compare("pass_balance", member_pass.id, member_pass.remaining_count, delta)
    payments = dict(
        db.session.query(Payment.settlement_id, db.func.sum(Payment.amount))
        .filter(Payment.kind == "payment")
        .group_by(Payment.settlement_id)
        .all()
    )
    refunds = dict(
        db.session.query(Payment.settlement_id, db.func.sum(Payment.amount))
        .filter(Payment.kind == "refund")
        .group_by(Payment.settlement_id)
        .all()
    )
    links = dict(
        db.session.query(SettlementVisit.settlement_id, db.func.sum(SettlementVisit.amount))
        .group_by(SettlementVisit.settlement_id)
        .all()
    )
    for settlement in Settlement.query.yield_per(500):
        compare("settlement_payment", settlement.id, settlement.paid_amount, payments.get(settlement.id, 0))
        compare("settlement_total", settlement.id, settlement.total_amount, links.get(settlement.id, 0))
        expected_refund = -Decimal(settlement.paid_amount) if settlement.status == "refunded" else Decimal(0)
        compare("settlement_refund", settlement.id, refunds.get(settlement.id, 0), expected_refund)
    for link, item_total in (
        db.session.query(SettlementVisit, db.func.coalesce(db.func.sum(OrderItem.total_amount), 0))
        .outerjoin(OrderItem, db.and_(OrderItem.visit_id == SettlementVisit.visit_id, OrderItem.status == "active"))
        .group_by(SettlementVisit.settlement_id, SettlementVisit.visit_id)
        .yield_per(500)
    ):
        compare("settled_order", link.visit_id, link.amount, item_total)

    def problem(code, item):
        nonlocal issue_count,checked
        checked+=1;issue_count+=1
        if len(issues)<100:
            issues.append({'kind':'order_billing','code':code,'entity_id':item.id,'visit_id':item.visit_id})

    visits={}
    for row in OrderItem.query.filter_by(status='active').order_by(OrderItem.created_at,OrderItem.id).yield_per(500):
        visits.setdefault(row.visit_id,[]).append(row)
        line=BillingLine(row.id,row.catalog_item_id or 'order:'+row.id,Decimal(row.quantity),Decimal(row.unit_price),0)
        try:
            expected=line_net_total(line,Decimal(row.covered_quantity or 0))
        except (ValueError,ArithmeticError):
            problem('ORDER_COVERAGE_BOUNDS',row)
            continue
        checked+=1
        if Decimal(row.total_amount)!=expected:
            problem('ORDER_NET_MISMATCH',row)
    for rows in visits.values():
        parents=[row for row in rows if row.kind=='package']
        if len(parents)>1:
            for row in parents: problem('PACKAGE_PARENT_DUPLICATE',row)
            continue
        parent=parents[0] if parents else None
        slots=[]
        if parent:
            if Decimal(parent.quantity)!=1 or Decimal(parent.covered_quantity or 0) or parent.package_order_item_id:
                problem('PACKAGE_PARENT_INVALID',parent)
            try:
                if not isinstance(parent.package_snapshot,dict): raise ValueError('missing snapshot')
                definition={key:value for key,value in parent.package_snapshot.items() if key!='reference_code'}
                slots=validate_package_definition(db.session,definition)
            except (ValueError,ArithmeticError,ApiError):
                problem('PACKAGE_SNAPSHOT_INVALID',parent)
                continue
        ordinary=[row for row in rows if row.kind!='package']
        lines=[BillingLine(row.id,row.catalog_item_id or 'order:'+row.id,Decimal(row.quantity),
            Decimal(row.unit_price),index) for index,row in enumerate(ordinary)]
        try:
            allocations=allocate_inclusions(lines,slots)
        except (ValueError,ArithmeticError):
            # Bound/number violations were already located above.
            continue
        for row in ordinary:
            expected=allocations[row.id]
            expected_parent=parent.id if parent and expected else None
            checked+=1
            if (Decimal(row.covered_quantity or 0)!=expected or row.package_order_item_id!=expected_parent
                    or (expected and parent.period_id!=row.period_id)):
                problem('PACKAGE_COVERAGE_MISMATCH',row)
    return {"valid": issue_count == 0, "checked": checked, "issue_count": issue_count, "issues": issues}
