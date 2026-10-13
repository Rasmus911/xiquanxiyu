"""Checkout member authorization and pass writes; caller owns the transaction."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .api.errors import ApiError
from .extensions import db
from .financial_lock import serialize_financial_session
from .member_card_models import MemberCardBinding, SettlementPassRedemption
from .models import Member, MemberPass, OrderItem, PassLedger
from .pass_billing import TicketCandidate, select_pass_tickets


@dataclass
class PassUsage:
    member_pass: MemberPass | None
    tickets: list[TicketCandidate]
    count: int
    amount: Decimal

    @property
    def member_pass_id(self):
        return self.member_pass.id if self.member_pass else None


def prepare_member_payment(visits, body, *, required, lock):
    if lock:
        serialize_financial_session(db.session)
    member_id = body.get('member_id') or next((row.member_id for row in visits if row.member_id), None)
    verification = body.get('member_verification')
    if not required and not verification:
        return None
    if not isinstance(member_id, str):
        raise ApiError('会员支付必须选择有效会员', code='INVALID_MEMBER')
    query = Member.query.filter_by(id=member_id, is_active=True).filter(Member.deleted_at.is_(None))
    member = (query.populate_existing().with_for_update() if lock else query).first()
    if not member:
        raise ApiError('会员支付必须选择有效会员', code='INVALID_MEMBER')
    if not member.phone and verification is None:
        raise ApiError('无手机号会员请读取实体卡', code='INVALID_MEMBER_VERIFICATION')
    if verification is not None:
        if not isinstance(verification, dict) or verification.get('method') not in ('phone', 'card'):
            raise ApiError('会员核实方式无效', code='INVALID_MEMBER_VERIFICATION')
        if verification['method'] == 'card':
            binding_id = verification.get('card_binding_id')
            if not isinstance(binding_id, str):
                raise ApiError('请重新读取有效实体卡', 409, 'INVALID_CARD_BINDING')
            query = MemberCardBinding.query.filter_by(id=binding_id, member_id=member.id, is_active=True)
            binding = (query.populate_existing().with_for_update() if lock else query).first()
            if not binding:
                raise ApiError('实体卡已失效或不属于当前会员', 409, 'INVALID_CARD_BINDING')
        elif not member.phone:
            raise ApiError('无手机号会员请读取实体卡', code='INVALID_MEMBER_VERIFICATION')
    if member.holder_surname and (not verification or verification.get('surname_confirmed') is not True):
        raise ApiError('请先确认持卡人姓氏', code='SURNAME_UNCONFIRMED')
    return member


def prepare_pass_usage(visits, selection, member, *, lock: bool) -> PassUsage:
    if lock:
        serialize_financial_session(db.session)
    if selection is None:
        return PassUsage(None, [], 0, Decimal('0.00'))
    if (not isinstance(selection, dict) or not isinstance(selection.get('member_pass_id'), str)
            or not isinstance(selection.get('visit_ids'), list)
            or any(not isinstance(value, str) for value in selection['visit_ids'])):
        raise ApiError('次卡抵扣选择无效', code='INVALID_PASS_SELECTION')
    selected_ids = selection['visit_ids']
    if not set(selected_ids).issubset({row.id for row in visits}):
        raise ApiError('抵次手牌必须在当前结账范围内', code='INVALID_PASS_SELECTION')
    if member is None:
        raise ApiError('请选择付款会员', code='INVALID_MEMBER')
    query = MemberPass.query.filter_by(id=selection['member_pass_id'], member_id=member.id, is_active=True)
    member_pass = (query.populate_existing().with_for_update() if lock else query).first()
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if not member_pass or (member_pass.valid_until and member_pass.valid_until < today):
        raise ApiError('次卡不存在、已停用或已过期', 409, 'PASS_UNAVAILABLE')
    rows = OrderItem.query.filter(OrderItem.visit_id.in_(selected_ids), OrderItem.kind == 'ticket').all()
    candidates = [TicketCandidate(row.visit_id, row.id, Decimal(row.total_amount), Decimal(row.quantity),
        Decimal(row.covered_quantity or 0), row.status) for row in rows]
    try:
        tickets = select_pass_tickets(candidates, selected_ids)
    except ValueError as error:
        raise ApiError(str(error), code='INVALID_PASS_SELECTION') from None
    if member_pass.remaining_count < len(tickets):
        raise ApiError('次卡剩余次数不足', 409, 'INSUFFICIENT_PASS')
    return PassUsage(member_pass, tickets, len(tickets), sum((row.amount for row in tickets), Decimal('0.00')))


def record_pass_usage(settlement, usage, employee):
    if not usage.count:
        return
    serialize_financial_session(db.session)
    member_pass = usage.member_pass
    member_pass.remaining_count -= usage.count
    member_pass.version += 1
    db.session.add(PassLedger(member_pass_id=member_pass.id, delta=-usage.count,
        balance_after=member_pass.remaining_count, entry_type='checkout_consume', amount_paid=0,
        settlement_id=settlement.id, operator_id=employee.id, note=f'结算单 {settlement.number}'))
    for ticket in usage.tickets:
        db.session.add(SettlementPassRedemption(settlement_id=settlement.id, visit_id=ticket.visit_id,
            order_item_id=ticket.order_item_id, member_pass_id=member_pass.id, count=1, amount=ticket.amount))


def refund_pass_usage(settlement, employee, reason):
    serialize_financial_session(db.session)
    if settlement.status != 'completed':
        raise ApiError('结算单不可返次', 409, 'NOT_REFUNDABLE')
    # Keep the source evidence forever; refunds append a separate zero-money ledger.
    redemptions = SettlementPassRedemption.query.filter_by(settlement_id=settlement.id).all()
    counts = {}
    for row in redemptions:
        counts[row.member_pass_id] = counts.get(row.member_pass_id, 0) + row.count
    if PassLedger.query.filter_by(settlement_id=settlement.id, entry_type='checkout_refund').first():
        raise ApiError('此结算单已返次', 409, 'NOT_REFUNDABLE')
    for pass_id in sorted(counts):
        member_pass = MemberPass.query.populate_existing().filter_by(id=pass_id).with_for_update().one()
        count = counts[pass_id]
        consumed = PassLedger.query.filter_by(settlement_id=settlement.id, member_pass_id=pass_id,
                                              entry_type='checkout_consume').all()
        if count <= 0 or sum(row.delta for row in consumed) != -count:
            raise ApiError('原始抵次记录不一致，请先核对', 409, 'PASS_RECONCILIATION_FAILED')
        member_pass.remaining_count += count
        member_pass.version += 1
        db.session.add(PassLedger(member_pass_id=pass_id, delta=count,
            balance_after=member_pass.remaining_count, entry_type='checkout_refund', amount_paid=0,
            settlement_id=settlement.id, operator_id=employee.id, note=reason))
