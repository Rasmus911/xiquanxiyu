from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.audit_service import verify_audit_chain
from app.extensions import db
from app.financial_integrity import check_financial_integrity
from app.member_card_models import SettlementPassRedemption
from app.models import AuditLog, Member, MemberPass, PassLedger, Payment, Settlement
from test_package_orders import open_visit, add
from test_pass_checkout051 import open_card, checkout_body


def settle(client, h, *, cash=True):
    visit = open_visit(client, h); card = open_card(client, h)
    if cash:
        add(client, h, visit, [('bath.scrub', 1)])
    response = client.post('/api/checkout', headers=h, json=checkout_body(card, [visit],
        payments=[{'method': 'cash', 'amount': '10'}] if cash else []))
    assert response.status_code == 201, response.get_json()
    return card, response.get_json()['data']['id']


def refund(client, session, settlement):
    return client.post('/api/checkout/' + settlement + '/refund', headers=session['headers'],
        json={'password': session['password'], 'reason': '隔离返次测试'})


@pytest.mark.parametrize('cash', [False, True])
def test_refund_restores_exact_original_count_once_even_expired_disabled(client, formal_catalog, strict_owner_session, cash):
    card, settlement = settle(client, strict_owner_session['headers'], cash=cash)
    member_pass = db.session.get(MemberPass, card['member_pass']['id'])
    member_pass.is_active = False; member_pass.valid_until = date(2020, 1, 1)
    db.session.commit()
    response = refund(client, strict_owner_session, settlement)
    assert response.status_code == 200, response.get_json()
    assert member_pass.remaining_count == 10
    assert SettlementPassRedemption.query.count() == 1
    assert PassLedger.query.filter_by(entry_type='checkout_consume').one().delta == -1
    restored = PassLedger.query.filter_by(entry_type='checkout_refund').one()
    assert (restored.delta, restored.amount_paid, restored.settlement_id) == (1, D(0), settlement)
    assert refund(client, strict_owner_session, settlement).status_code == 409
    assert PassLedger.query.filter_by(entry_type='checkout_refund').count() == 1
    assert Payment.query.filter_by(kind='refund').count() == int(cash)
    assert check_financial_integrity()['valid'] is True
    assert verify_audit_chain() == (True, None)


def test_refund_database_failure_rolls_back_payments_balance_pass_and_audit(client, formal_catalog, strict_owner_session):
    h = strict_owner_session['headers']; visit = open_visit(client, h); card = open_card(client, h)
    add(client, h, visit, [('bath.scrub', 1)])
    assert client.post('/api/members/' + card['member']['id'] + '/recharge', headers=h,
        json={'amount': '5', 'payment_method': 'cash', 'idempotency_key': 'refund-recharge'}).status_code == 200
    response = client.post('/api/checkout', headers=h, json=checkout_body(card, [visit],
        payments=[{'method': 'balance', 'amount': '5'}, {'method': 'cash', 'amount': '5'}]))
    assert response.status_code == 201
    settlement = response.get_json()['data']['id']; audits = AuditLog.query.count()
    # Real database rejection late in the refund transaction, after balances/payments are staged.
    db.session.connection().execute(text("CREATE TRIGGER reject_pass_refund BEFORE INSERT ON pass_ledgers WHEN NEW.entry_type = 'checkout_refund' BEGIN SELECT RAISE(ABORT, 'isolated refund failure'); END"))
    db.session.commit()
    response = refund(client, strict_owner_session, settlement)
    assert response.status_code == 409
    assert db.session.get(Settlement, settlement).status == 'completed'
    assert db.session.get(MemberPass, card['member_pass']['id']).remaining_count == 9
    assert db.session.get(Member, card['member']['id']).balance == 0
    assert Payment.query.filter_by(kind='refund').count() == 0
    assert AuditLog.query.filter_by(action='checkout.refund').count() == 0
    assert AuditLog.query.count() == audits + 1  # rejected request security audit survives rollback
    assert AuditLog.query.order_by(AuditLog.chain_index.desc()).first().action == 'security.request_denied'
    assert PassLedger.query.filter_by(entry_type='checkout_refund').count() == 0


def test_report_receipt_and_integrity_distinguish_face_value_from_cash(client, formal_catalog, strict_owner_session):
    h = strict_owner_session['headers']; card, settlement = settle(client, h)
    receipt = client.get('/api/checkout/' + settlement + '/receipt', headers=h).get_json()['data']
    assert receipt['settlement']['pass_redemption_amount'] == '15.00'
    assert receipt['settlement']['pass_redemption_count'] == 1
    assert receipt['settlement']['total_amount'] == '25.00'
    assert receipt['settlement']['amount_due'] == '10.00'
    assert receipt['settlement']['member_card'] == {'card_uid': '000315346091', 'holder_surname': '张'}
    assert receipt['visits'][0]['amount'] == '25.00'
    assert check_financial_integrity()['valid'] is True
    start = datetime.now(timezone.utc) - timedelta(days=1); end = start + timedelta(days=3)
    query = {'start': start.isoformat(), 'end': end.isoformat()}
    report = client.get('/api/reports/summary', headers=h, query_string=query).get_json()['data']
    assert (report['gross_sales'], report['operating_revenue'], report['actual_cash_inflow']) == ('25.00', '25.00', '110.00')
    assert refund(client, strict_owner_session, settlement).status_code == 200
    report = client.get('/api/reports/summary', headers=h, query_string=query).get_json()['data']
    assert (report['refund_total'], report['operating_revenue'], report['actual_cash_inflow']) == ('25.00', '0.00', '100.00')
    trend = client.get('/api/reports/trend', headers=h, query_string=query).get_json()['data']
    assert sum(D(row['revenue']) for row in trend) == 0
    assert sum(D(row['cash_inflow']) for row in trend) == 100


@pytest.mark.parametrize('mutation,kind', [('amount', 'settlement_funding'), ('consume', 'pass_checkout_consume'), ('refund', 'pass_checkout_refund'), ('cash', 'pass_checkout_cash')])
def test_integrity_detects_redemption_and_ledger_mismatch(client, formal_catalog, strict_owner_session, mutation, kind):
    card, settlement = settle(client, strict_owner_session['headers'])
    if mutation == 'amount':
        original = SettlementPassRedemption.query.one()
        db.session.add(SettlementPassRedemption(settlement_id=settlement, visit_id=original.visit_id,
            order_item_id=original.order_item_id, member_pass_id=original.member_pass_id, count=1, amount=D(14)))
    else:
        db.session.add(PassLedger(member_pass_id=card['member_pass']['id'], settlement_id=settlement,
            operator_id=strict_owner_session['owner_id'], balance_after=9,
            delta=1 if mutation == 'refund' else (-1 if mutation == 'consume' else 0),
            amount_paid=15 if mutation == 'cash' else 0,
            entry_type='checkout_refund' if mutation == 'refund' else 'checkout_consume'))
    db.session.commit()
    result = check_financial_integrity()
    assert result['valid'] is False
    assert kind in {issue['kind'] for issue in result['issues']}


def test_two_ticket_refund_restores_two_and_receipt_keeps_original_card_after_replacement(client, formal_catalog, strict_owner_session):
    h = strict_owner_session['headers']; first = open_visit(client, h); second = open_visit(client, h, '002')
    card = open_card(client, h)
    response = client.post('/api/checkout', headers=h, json=checkout_body(card, [first, second]))
    assert response.status_code == 201
    settlement = response.get_json()['data']['id']
    assert client.post('/api/members/' + card['member']['id'] + '/physical-card', headers=h, json={
        'password': strict_owner_session['password'], 'card_uid': '444', 'idempotency_key': 'replace'}).status_code == 200
    receipt = client.get('/api/checkout/' + settlement + '/receipt', headers=h).get_json()['data']
    assert receipt['settlement']['member_card']['card_uid'] == '000315346091'
    assert refund(client, strict_owner_session, settlement).status_code == 200
    assert db.session.get(MemberPass, card['member_pass']['id']).remaining_count == 10
    assert PassLedger.query.filter_by(entry_type='checkout_refund').one().delta == 2
    assert check_financial_integrity()['valid'] is True
