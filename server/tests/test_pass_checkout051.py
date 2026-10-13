from decimal import Decimal as D

import pytest

from app.pass_billing import TicketCandidate, select_pass_tickets
from app.extensions import db
from app.models import Member, MemberPass, OrderItem, PassLedger, Payment, Settlement, SettlementVisit, StoredValueLedger, Visit, Wristband
from app.member_card_models import MemberCardBinding, SettlementPassRedemption
from test_package_orders import open_visit, add, item, package


def open_card(client, headers, uid='000315346091'):
    response = client.post('/api/members/physical-open', headers=headers, json={
        'card_uid': uid, 'phone': None, 'holder_surname': '张', 'surname_confirmed': True,
        'membership_type': 'pass', 'amount': '100', 'count': 10, 'pass_name': '洗浴次卡',
        'payment_method': 'cash', 'idempotency_key': 'open-' + uid})
    assert response.status_code == 201, response.get_json()
    return response.get_json()['data']


def checkout_body(card, visits, selected=None, payments=None):
    return {'visit_ids': visits, 'checkout_scope': 'selected', 'member_id': card['member']['id'],
        'pass_use': {'member_pass_id': card['member_pass']['id'], 'visit_ids': selected or visits},
        'member_verification': {'method': 'card', 'card_binding_id': card['card_binding']['id'], 'surname_confirmed': True},
        'payments': payments or [], 'idempotency_key': 'pass-checkout'}


def assert_untouched(visit_ids, card):
    assert all(db.session.get(Visit, value).status == 'open' for value in visit_ids)
    assert all(db.session.get(Wristband, db.session.get(Visit, value).wristband_id).status == 'in_use' for value in visit_ids)
    assert Settlement.query.count() == Payment.query.count() == SettlementPassRedemption.query.count() == 0
    assert PassLedger.query.filter_by(entry_type='checkout_consume').count() == 0
    assert StoredValueLedger.query.filter_by(entry_type='consume').count() == 0


def test_ticket_plus_service_preview_complete_and_immutable_retry(client, formal_catalog, strict_owner_session):
    h = strict_owner_session['headers']; visit = open_visit(client, h); card = open_card(client, h)
    add(client, h, visit, [('bath.scrub', 1)])
    body = checkout_body(card, [visit], payments=[{'method': 'cash', 'amount': '10'}])
    preview = client.post('/api/checkout/preview', headers=h, json=body)
    assert preview.status_code == 200, preview.get_json()
    data = preview.get_json()['data']
    assert (data['total_amount'], data['pass_redemption_amount'], data['pass_redemption_count'], data['amount_due']) == ('25.00', '15.00', 1, '10.00')
    assert_untouched([visit], card)
    completed = client.post('/api/checkout', headers=h, json=body)
    assert completed.status_code == 201, completed.get_json()
    result = completed.get_json()['data']
    assert (result['total_amount'], result['paid_amount'], result['amount_due']) == ('25.00', '10.00', '10.00')
    assert result['pass_redemptions'][0]['amount'] == '15.00'
    assert SettlementVisit.query.one().amount == D(25)
    assert db.session.get(MemberPass, card['member_pass']['id']).remaining_count == 9
    ledger = PassLedger.query.filter_by(entry_type='checkout_consume').one()
    assert (ledger.delta, ledger.amount_paid, ledger.settlement_id) == (-1, D(0), result['id'])
    assert client.post('/api/checkout', headers=h, json=body).get_json()['data'] == result
    assert PassLedger.query.filter_by(entry_type='checkout_consume').count() == 1
    for mutation in [{'pass_use': {**body['pass_use'], 'member_pass_id': 'changed'}},
                     {'pass_use': {**body['pass_use'], 'visit_ids': []}}, {'member_id': 'changed'},
                     {'member_verification': {**body['member_verification'], 'card_binding_id': 'changed'}}]:
        response = client.post('/api/checkout', headers=h, json={**body, **mutation})
        assert response.status_code == 409
        assert response.get_json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


@pytest.mark.parametrize('child', [False, True])
def test_all_ticket_checkout_has_no_fake_cash_and_uses_real_ticket_price(client, formal_catalog, strict_owner_session, child):
    h = strict_owner_session['headers']; visit = open_visit(client, h); card = open_card(client, h)
    if child:
        response = client.patch(f'/api/visits/{visit}/ticket', headers=h, json={
            'ticket_catalog_item_id': item('ticket.child').id, 'idempotency_key': 'child',
            'version': db.session.get(Visit, visit).version})
        assert response.status_code == 200
    body = checkout_body(card, [visit]); body['pass_use']['amount'] = '999.00'
    response = client.post('/api/checkout', headers=h, json=body)
    assert response.status_code == 201, response.get_json()
    data = response.get_json()['data']
    assert data['pass_redemption_amount'] == ('10.00' if child else '15.00')
    assert data['paid_amount'] == '0.00' and data['payments'] == [] and Payment.query.count() == 0


def test_two_visits_only_selected_ticket_redeemed_and_partial_balance_with_cash(client, formal_catalog, strict_owner_session):
    h = strict_owner_session['headers']; first = open_visit(client, h); second = open_visit(client, h, '002'); card = open_card(client, h)
    assert client.post('/api/members/' + card['member']['id'] + '/recharge', headers=h,
        json={'amount': '5', 'payment_method': 'wechat', 'idempotency_key': 'recharge'}).status_code == 200
    body = checkout_body(card, [first, second], [second], [{'method': 'balance', 'amount': '5'}, {'method': 'cash', 'amount': '10'}])
    response = client.post('/api/checkout', headers=h, json=body)
    assert response.status_code == 201, response.get_json()
    assert response.get_json()['data']['total_amount'] == '30.00'
    assert SettlementPassRedemption.query.one().visit_id == second
    assert db.session.get(Member, card['member']['id']).balance == 0
    assert db.session.get(MemberPass, card['member_pass']['id']).remaining_count == 9
    assert {row.method: row.amount for row in Payment.query.all()} == {'cash': D(10), 'balance': D(5)}


@pytest.mark.parametrize('failure', ['covered', 'outside', 'duplicate', 'insufficient_pass', 'balance', 'binding', 'surname', 'expired', 'inactive', 'foreign_pass'])
def test_invalid_redemption_is_atomic(client, formal_catalog, strict_owner_session, failure):
    from datetime import date
    h = strict_owner_session['headers']; visit = open_visit(client, h); card = open_card(client, h)
    body = checkout_body(card, [visit])
    if failure == 'covered':
        assert package(client, h, visit).status_code == 200
        body['payments'] = [{'method': 'cash', 'amount': '30'}]
    elif failure == 'outside': body['pass_use']['visit_ids'] = ['outside']
    elif failure == 'duplicate': body['pass_use']['visit_ids'] = [visit, visit]
    elif failure == 'insufficient_pass': db.session.get(MemberPass, card['member_pass']['id']).remaining_count = 0
    elif failure == 'balance':
        add(client, h, visit, [('bath.scrub', 1)])
        body['payments'] = [{'method': 'balance', 'amount': '10'}]
    elif failure == 'binding': db.session.get(MemberCardBinding, card['card_binding']['id']).is_active = False
    elif failure == 'surname': body['member_verification']['surname_confirmed'] = False
    elif failure == 'expired': db.session.get(MemberPass, card['member_pass']['id']).valid_until = date(2020, 1, 1)
    elif failure == 'inactive': db.session.get(MemberPass, card['member_pass']['id']).is_active = False
    elif failure == 'foreign_pass': body['pass_use']['member_pass_id'] = open_card(client, h, '222')['member_pass']['id']
    db.session.commit()
    before = [(row.id, row.total_amount, row.status) for row in OrderItem.query.all()]
    response = client.post('/api/checkout', headers=h, json=body)
    assert response.status_code in (400, 409), response.get_json()
    expected = {'covered': 'INVALID_PASS_SELECTION', 'outside': 'INVALID_PASS_SELECTION',
        'duplicate': 'INVALID_PASS_SELECTION', 'insufficient_pass': 'INSUFFICIENT_PASS',
        'balance': 'INSUFFICIENT_BALANCE', 'binding': 'INVALID_CARD_BINDING',
        'surname': 'SURNAME_UNCONFIRMED', 'expired': 'PASS_UNAVAILABLE',
        'inactive': 'PASS_UNAVAILABLE', 'foreign_pass': 'PASS_UNAVAILABLE'}
    assert response.get_json()['error']['code'] == expected[failure]
    assert_untouched([visit], card)
    assert [(row.id, row.total_amount, row.status) for row in OrderItem.query.all()] == before


def test_pass_only_covers_uncovered_ticket_for_selected_visit():
    valid = TicketCandidate('v1', 'ticket1', D('15'), D(1), D(0), 'active')
    covered = TicketCandidate('v2', 'ticket2', D(0), D(1), D(1), 'active')
    assert select_pass_tickets([valid, covered], ['v1']) == [valid]
    with pytest.raises(ValueError):
        select_pass_tickets([valid, covered], ['v2'])
    with pytest.raises(ValueError):
        select_pass_tickets([valid], ['v1', 'v1'])


@pytest.mark.parametrize('tickets', [[], [TicketCandidate('v', 't', D(15), D(2), D(0), 'active')],
    [TicketCandidate('v', 't', D(15), D(1), D('.5'), 'active')],
    [TicketCandidate('v', 't', D(15), D(1), D(0), 'void')],
    [TicketCandidate('v', 't', D(0), D(1), D(0), 'active')],
    [TicketCandidate('v', value, D(15), D(1), D(0), 'active') for value in ['a', 'b']]])
def test_selector_rejects_ambiguous_or_non_independent_ticket(tickets):
    with pytest.raises(ValueError):
        select_pass_tickets(tickets, ['v'])


@pytest.mark.parametrize('changed', ['pass', 'binding', 'balance', 'member'])
def test_complete_revalidates_resources_after_valid_preview(client, formal_catalog, strict_owner_session, changed):
    h = strict_owner_session['headers']; visit = open_visit(client, h); card = open_card(client, h)
    add(client, h, visit, [('bath.scrub', 1)])
    assert client.post('/api/members/' + card['member']['id'] + '/recharge', headers=h,
        json={'amount': '10', 'payment_method': 'cash', 'idempotency_key': 'preview-recharge'}).status_code == 200
    body = checkout_body(card, [visit], payments=[{'method': 'balance', 'amount': '10'}])
    assert client.post('/api/checkout/preview', headers=h, json=body).status_code == 200
    if changed == 'pass': db.session.get(MemberPass, card['member_pass']['id']).remaining_count = 0
    elif changed == 'binding': db.session.get(MemberCardBinding, card['card_binding']['id']).is_active = False
    elif changed == 'balance': db.session.get(Member, card['member']['id']).balance = 0
    else: db.session.get(Member, card['member']['id']).is_active = False
    db.session.commit()
    denied = client.post('/api/checkout', headers=h, json=body)
    assert denied.status_code in (400, 409)
    assert_untouched([visit], card)


def test_late_checkout_database_failure_rolls_back_consumption_and_close(client, formal_catalog, strict_owner_session):
    from sqlalchemy import text
    h = strict_owner_session['headers']; visit = open_visit(client, h); card = open_card(client, h)
    add(client, h, visit, [('bath.scrub', 1)])
    db.session.connection().execute(text("CREATE TRIGGER reject_checkout_payment BEFORE INSERT ON payments BEGIN SELECT RAISE(ABORT, 'isolated checkout failure'); END"))
    db.session.commit()
    body = checkout_body(card, [visit], payments=[{'method': 'cash', 'amount': '10'}])
    assert client.post('/api/checkout', headers=h, json=body).status_code == 409
    assert_untouched([visit], card)
    assert db.session.get(MemberPass, card['member_pass']['id']).remaining_count == 10
    # The failed attempt also rolls back its idempotency placeholder.
    db.session.connection().execute(text('DROP TRIGGER reject_checkout_payment'))
    db.session.commit()
    assert client.post('/api/checkout', headers=h, json=body).status_code == 201


def test_ticket_kind_is_authoritative_even_when_name_still_says_ticket(client, formal_catalog, strict_owner_session):
    h = strict_owner_session['headers']; visit = open_visit(client, h); card = open_card(client, h)
    ticket = OrderItem.query.filter_by(visit_id=visit, kind='ticket').one()
    ticket.kind = 'service'
    db.session.commit()
    response = client.post('/api/checkout', headers=h, json=checkout_body(card, [visit]))
    assert response.status_code == 400
    assert response.get_json()['error']['code'] == 'INVALID_PASS_SELECTION'
    assert_untouched([visit], card)


def test_no_phone_card_cannot_skip_binding_verification_when_surname_is_blank(client, formal_catalog, strict_owner_session):
    h = strict_owner_session['headers']; visit = open_visit(client, h); card = open_card(client, h)
    db.session.get(Member, card['member']['id']).holder_surname = None
    db.session.get(MemberCardBinding, card['card_binding']['id']).is_active = False
    db.session.commit()
    body = checkout_body(card, [visit]); body['member_verification'] = None
    response = client.post('/api/checkout', headers=h, json=body)
    assert response.status_code == 400
    assert response.get_json()['error']['code'] == 'INVALID_MEMBER_VERIFICATION'
    assert_untouched([visit], card)
