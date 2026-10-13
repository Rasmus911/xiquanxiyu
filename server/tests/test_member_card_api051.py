from decimal import Decimal

import pytest

from app.extensions import db
from app.member_card_models import MemberCardBinding
from app.models import AuditLog, IdempotencyRecord, Member, MemberPass, PassLedger, StoredValueLedger


def opening(**changes):
    return {**dict(card_uid='000315346091', phone=None, holder_surname=None,
                   surname_confirmed=False, membership_type='stored', amount='100.00',
                   payment_method='cash', idempotency_key='physical-open-051'), **changes}


def post_open(client, session, body):
    return client.post('/api/members/physical-open', headers=session['headers'], json=body)


def test_paid_open_without_phone_is_atomic_and_idempotent(client, strict_owner_session):
    # Missing atomic opening/replay would duplicate the account or collected money.
    body = opening()
    first = post_open(client, strict_owner_session, body)
    assert first.status_code == 201, first.get_json()
    repeated = post_open(client, strict_owner_session, body)
    assert repeated.status_code == 200, repeated.get_json()
    a, b = first.get_json()['data'], repeated.get_json()['data']
    assert a == b
    assert b['member']['phone'] == ''
    assert b['member']['balance'] == '100.00'
    assert b['card_binding']['card_uid'] == '000315346091'
    assert b['member_pass'] is None
    assert Member.query.count() == MemberCardBinding.query.count() == StoredValueLedger.query.count() == 1
    assert Member.query.one().phone is None
    assert IdempotencyRecord.query.count() == 1


@pytest.mark.parametrize('changes', [
    {'amount': '0'}, {'amount': '-1'}, {'amount': 'NaN'}, {'amount': '1.001'},
    {'payment_method': 'balance'}, {'membership_type': 'unknown'},
    {'card_uid': 315346091}, {'card_uid': '１２３'}, {'card_uid': '1' * 65},
    {'holder_surname': '张', 'surname_confirmed': False},
    {'holder_surname': '张', 'surname_confirmed': 'true'},
    {'holder_surname': '张' * 41, 'surname_confirmed': True},
    {'phone': '123'}, {'idempotency_key': ''},
    {'membership_type': 'pass', 'count': 0},
    {'membership_type': 'pass', 'count': 1.5},
    {'membership_type': 'pass', 'count': True},
    {'membership_type': 'pass', 'count': 10, 'valid_until': '2026-02-30'},
])
def test_invalid_open_leaves_no_paid_state(client, strict_owner_session, changes):
    # Validation must precede persistent collection/account effects.
    response = post_open(client, strict_owner_session, opening(**changes))
    assert response.status_code == 400, response.get_json()
    assert Member.query.count() == MemberCardBinding.query.count() == 0
    assert StoredValueLedger.query.count() == PassLedger.query.count() == 0
    assert MemberPass.query.count() == IdempotencyRecord.query.count() == 0


def test_pass_sale_records_amount_and_returns_eligible_pass(client, strict_owner_session):
    # A count-only issue would lose real collected cash; lookup must not consume.
    body = opening(membership_type='pass', count=10, amount='300.00', payment_method='wechat',
                   holder_surname='欧阳', surname_confirmed=True, pass_name='十次洗浴',
                   valid_until='2099-12-31')
    first = post_open(client, strict_owner_session, body)
    assert first.status_code == 201, first.get_json()
    data = first.get_json()['data']
    assert data['member']['balance'] == '0.00'
    assert data['member']['holder_surname'] == '欧阳'
    assert data['member_pass']['remaining_count'] == 10
    assert data['member_pass']['name'] == '十次洗浴'
    repeated = post_open(client, strict_owner_session, body)
    assert repeated.status_code == 200
    assert repeated.get_json()['data'] == data
    ledger = PassLedger.query.one()
    assert (ledger.entry_type, ledger.delta, ledger.balance_after, ledger.amount_paid,
            ledger.payment_method) == ('issue', 10, 10, Decimal('300.00'), 'wechat')
    assert StoredValueLedger.query.count() == 0
    lookup = client.get('/api/members/lookup', headers=strict_owner_session['headers'],
                        query_string={'card_uid': '000315346091'})
    assert lookup.status_code == 200, lookup.get_json()
    assert lookup.get_json()['data']['passes'] == [data['member_pass']]
    assert MemberPass.query.one().remaining_count == 10


def test_same_key_changed_body_and_duplicate_open_do_not_collect(client, strict_owner_session):
    # Replays compare body before UID/phone conflicts; new keys cannot recollect.
    original = post_open(client, strict_owner_session, opening(phone='13800000000'))
    assert original.status_code == 201, original.get_json()
    for body, code in [
        (opening(phone='13800000000', amount='200.00'), 'IDEMPOTENCY_CONFLICT'),
        (opening(phone='13900000000', idempotency_key='second'), 'CARD_IN_USE'),
        (opening(phone='13800000000', card_uid='0999', idempotency_key='third'), 'PHONE_EXISTS'),
    ]:
        response = post_open(client, strict_owner_session, body)
        assert response.status_code == 409, response.get_json()
        assert response.get_json()['error']['code'] == code
    assert Member.query.count() == MemberCardBinding.query.count() == StoredValueLedger.query.count() == 1
    assert IdempotencyRecord.query.count() == 1
    assert Member.query.one().balance == Decimal('100.00')


def test_open_replay_returns_original_balance_after_recharge(client, strict_owner_session):
    # Replays return captured result rather than mutable present-day balances.
    first = post_open(client, strict_owner_session, opening())
    assert first.status_code == 201, first.get_json()
    data = first.get_json()['data']
    recharge = client.post(f"/api/members/{data['member']['id']}/recharge",
        headers=strict_owner_session['headers'], json={'amount': '50.00',
            'payment_method': 'cash', 'idempotency_key': 'later-recharge'})
    assert recharge.status_code == 200, recharge.get_json()
    replay = post_open(client, strict_owner_session, opening())
    assert replay.status_code == 200
    assert replay.get_json()['data'] == data
    assert Member.query.one().balance == Decimal('150.00')


def test_audit_failure_rolls_back_account_binding_and_collection(client, strict_owner_session, monkeypatch):
    # Inject failure after real account and ledger writes, preserving DB transaction.
    from app.api.errors import ApiError
    def fail_audit(*args, **kwargs):
        raise ApiError('isolated audit failure', 503, 'TEST_AUDIT_FAILED')
    monkeypatch.setattr('app.member_cards.write_audit', fail_audit)
    response = post_open(client, strict_owner_session, opening())
    assert response.status_code == 503, response.get_json()
    assert Member.query.count() == MemberCardBinding.query.count() == 0
    assert StoredValueLedger.query.count() == IdempotencyRecord.query.count() == 0
    monkeypatch.undo()
    assert post_open(client, strict_owner_session, opening()).status_code == 201


def test_phone_and_card_resolve_same_account(client, strict_owner_session):
    # Optional phone and physical card must address a single financial account.
    first = post_open(client, strict_owner_session, opening(phone='138-0000-0000'))
    assert first.status_code == 201, first.get_json()
    data = first.get_json()['data']
    found = []
    for query in ({'phone': '13800000000'}, {'card_uid': ' 000315346091 '}):
        response = client.get('/api/members/lookup', headers=strict_owner_session['headers'], query_string=query)
        assert response.status_code == 200, response.get_json()
        found.append(response.get_json()['data'])
    assert found[0] == found[1]
    assert found[0]['id'] == data['member']['id']
    assert found[0]['card_binding'] == data['card_binding']


@pytest.mark.parametrize('query,code,status', [
    ({}, 'INVALID_LOOKUP', 400),
    ({'phone': '13800000000', 'card_uid': '001'}, 'INVALID_LOOKUP', 400),
    ({'phone': ''}, 'BAD_REQUEST', 400),
    ({'card_uid': 'unknown'}, 'INVALID_CARD_UID', 400),
    ({'card_uid': '00999'}, 'CARD_NOT_FOUND', 404),
])
def test_lookup_requires_exactly_one_valid_identifier(client, strict_owner_session, query, code, status):
    response = client.get('/api/members/lookup', headers=strict_owner_session['headers'], query_string=query)
    assert response.status_code == status, response.get_json()
    assert response.get_json()['error']['code'] == code


def bind(client, session, member_id, **changes):
    body = {'card_uid': '0002', 'password': session['password'], 'idempotency_key': 'replace-051', **changes}
    return client.post(f'/api/members/{member_id}/physical-card', headers=session['headers'], json=body)


def test_replace_revokes_old_card_preserves_rights_and_replays_original(client, strict_owner_session):
    # Replacement revokes old UID atomically without moving money/count rights.
    first = post_open(client, strict_owner_session, opening(membership_type='pass', count=7))
    assert first.status_code == 201, first.get_json()
    data = first.get_json()['data']
    member_id = data['member']['id']
    replaced = bind(client, strict_owner_session, member_id)
    assert replaced.status_code == 200, replaced.get_json()
    result = replaced.get_json()['data']
    old = db.session.get(MemberCardBinding, data['card_binding']['id'])
    assert not old.is_active and old.revoked_at is not None
    assert old.replaced_by_id == result['card_binding']['id']
    assert MemberPass.query.one().remaining_count == 7
    assert PassLedger.query.count() == 1
    assert Member.query.one().balance == Decimal('0.00')
    second = bind(client, strict_owner_session, member_id, card_uid='0003', idempotency_key='replace-again')
    assert second.status_code == 200, second.get_json()
    replay = bind(client, strict_owner_session, member_id)
    assert replay.status_code == 200
    assert replay.get_json()['data'] == result
    assert MemberCardBinding.query.filter_by(is_active=True).one().card_uid == '0003'
    old_lookup = client.get('/api/members/lookup', headers=strict_owner_session['headers'],
                            query_string={'card_uid': '000315346091'})
    assert old_lookup.status_code == 409
    assert old_lookup.get_json()['error']['code'] == 'CARD_REVOKED'
    reenable = bind(client, strict_owner_session, member_id, card_uid='000315346091', idempotency_key='reenable')
    assert reenable.status_code == 409
    assert reenable.get_json()['error']['code'] == 'CARD_REVOKED'
    assert IdempotencyRecord.query.count() == 3
    assert bind(client, strict_owner_session, member_id, card_uid='004').status_code == 409
    password = strict_owner_session['password']
    assert all(password not in str(row.response_body) for row in IdempotencyRecord.query.all())
    assert all(password not in str(row.details) for row in AuditLog.query.all())


def test_bad_password_does_not_commit_pending_idempotency_or_mutate_card(client, strict_owner_session):
    # Sensitive-password failure commits its counter; no pending card rows may exist.
    first = post_open(client, strict_owner_session, opening())
    assert first.status_code == 201, first.get_json()
    member_id = first.get_json()['data']['member']['id']
    failed = bind(client, strict_owner_session, member_id, password='wrong-password')
    assert failed.status_code == 403, failed.get_json()
    assert failed.get_json()['error']['code'] == 'REAUTH_FAILED'
    assert IdempotencyRecord.query.count() == 1
    assert MemberCardBinding.query.one().is_active
    assert Member.query.one().balance == Decimal('100.00')
    assert bind(client, strict_owner_session, member_id).status_code == 200
    assert IdempotencyRecord.query.count() == 2
    assert Member.query.one().balance == Decimal('100.00')
    assert StoredValueLedger.query.count() == 1


def test_binding_existing_phone_account_and_conflict_preserves_old_card(client, strict_owner_session):
    # Existing phone account can gain a card; a UID owned elsewhere cannot revoke it.
    headers = strict_owner_session['headers']
    created = client.post('/api/members', headers=headers, json={'phone': '13800000000'})
    member_id = created.get_json()['data']['id']
    assert bind(client, strict_owner_session, member_id).status_code == 200
    paid = post_open(client, strict_owner_session, opening())
    assert paid.status_code == 201, paid.get_json()
    conflict = bind(client, strict_owner_session, member_id, card_uid='000315346091', idempotency_key='conflict')
    assert conflict.status_code == 409
    assert MemberCardBinding.query.filter_by(member_id=member_id, is_active=True).one().card_uid == '0002'
    assert Member.query.filter_by(id=member_id).one().balance == 0


def test_archive_revokes_binding_and_lookup_rejects_account(client, strict_owner_session):
    # Archive must revoke card in same transaction and deny phone identification.
    headers = strict_owner_session['headers']
    created = client.post('/api/members', headers=headers, json={'phone': '13800000000'})
    member_id = created.get_json()['data']['id']
    assert bind(client, strict_owner_session, member_id).status_code == 200
    response = client.delete(f'/api/members/{member_id}', headers=headers,
                             json={'password': strict_owner_session['password']})
    assert response.status_code == 200, response.get_json()
    assert not MemberCardBinding.query.one().is_active
    for query, code in [({'phone': '13800000000'}, 'MEMBER_NOT_FOUND'), ({'card_uid': '0002'}, 'CARD_REVOKED')]:
        found = client.get('/api/members/lookup', headers=headers, query_string=query)
        assert found.status_code in (404, 409)
        assert found.get_json()['error']['code'] == code


def test_name_search_does_not_match_every_member(client, strict_owner_session):
    # Pure-name search must not construct phone ILIKE %% matching unrelated accounts.
    headers = strict_owner_session['headers']
    for phone, name in [('13800000000', '张三'), ('13900000000', '李四')]:
        assert client.post('/api/members', headers=headers, json={'phone': phone, 'name': name}).status_code == 201
    rows = client.get('/api/members', headers=headers, query_string={'keyword': '张'}).get_json()['data']
    assert [row['name'] for row in rows] == ['张三']


def test_unprivileged_employee_cannot_open_bind_or_lookup(client, strict_owner_session, desktop050_employee_session):
    # Client role claims cannot bypass actual employee permissions.
    worker = desktop050_employee_session(role='male_scrubber')
    member = client.post('/api/members', headers=strict_owner_session['headers'], json={'phone': '13800000000'}).get_json()['data']
    responses = [post_open(client, worker, opening()),
                 bind(client, worker, member['id']),
                 client.get('/api/members/lookup', headers=worker['headers'], query_string={'card_uid': '0002'})]
    assert [response.status_code for response in responses] == [403, 403, 403]
    assert MemberCardBinding.query.count() == StoredValueLedger.query.count() == 0


def test_no_phone_skips_customer_sms_but_not_admin(client, strict_owner_session, app, monkeypatch):
    # Only external SMS transport is doubled; real notification selection/audit runs.
    deliveries = []
    def transport(phone, template, params, recipient):
        deliveries.append((phone, recipient))
        return {'recipient': recipient, 'success': True, 'status': 'sent', 'message': 'submitted'}
    monkeypatch.setattr('app.sms_service.send_template_sms', transport)
    app.config['SMS_ADMIN_PHONE'] = '18600000001,18600000002'
    result = post_open(client, strict_owner_session, opening())
    assert result.status_code == 201, result.get_json()
    assert deliveries == [('18600000001', 'admin'), ('18600000002', 'admin')]
    assert AuditLog.query.filter_by(action='member.card_sms').count() == 2
    assert post_open(client, strict_owner_session, opening()).status_code == 200
    assert len(deliveries) == 2


def test_notification_exception_cannot_undo_or_repeat_collection(client, strict_owner_session, monkeypatch):
    # A post-commit external failure must still return captured paid result.
    def transport(*args, **kwargs):
        raise RuntimeError('isolated SMS outage')
    monkeypatch.setattr('app.sms_service.send_template_sms', transport)
    body = opening(phone='13800000000')
    first = post_open(client, strict_owner_session, body)
    assert first.status_code == 201, first.get_json()
    repeated = post_open(client, strict_owner_session, body)
    assert repeated.status_code == 200
    assert first.get_json()['data'] == repeated.get_json()['data']
    assert Member.query.one().balance == Decimal('100.00')
    assert StoredValueLedger.query.count() == 1


@pytest.mark.parametrize('changes', [{'membership_type': ['stored']}, {'payment_method': {'cash': True}}])
def test_malformed_type_is_validation_error_not_server_error(client, strict_owner_session, changes):
    # JSON collections in scalar fields must fail validation without raising TypeError.
    response = post_open(client, strict_owner_session, opening(**changes))
    assert response.status_code == 400, response.get_json()
    assert Member.query.count() == StoredValueLedger.query.count() == IdempotencyRecord.query.count() == 0


def test_replacement_audit_failure_restores_original_binding(client, strict_owner_session, monkeypatch):
    # An error after revoking/inserting cards rolls both mutations back together.
    from app.api.errors import ApiError
    first = post_open(client, strict_owner_session, opening())
    assert first.status_code == 201
    member_id = first.get_json()['data']['member']['id']
    def fail_audit(*args, **kwargs):
        raise ApiError('isolated replacement audit failure', 503, 'TEST_AUDIT_FAILED')
    monkeypatch.setattr('app.member_cards.write_audit', fail_audit)
    failed = bind(client, strict_owner_session, member_id)
    assert failed.status_code == 503, failed.get_json()
    old = MemberCardBinding.query.one()
    assert old.is_active and old.revoked_at is None and old.replaced_by_id is None
    assert IdempotencyRecord.query.count() == 1
    assert Member.query.one().balance == Decimal('100.00')


def test_lookup_excludes_disabled_empty_and_expired_passes(client, strict_owner_session):
    # Lookup must offer only usable rights, without auto-consuming them.
    from datetime import date
    member = client.post('/api/members', headers=strict_owner_session['headers'],
                         json={'phone': '13800000000'}).get_json()['data']
    for name, count, active, until in [('eligible', 3, True, None), ('empty', 0, True, None),
                                     ('disabled', 2, False, None), ('expired', 2, True, date(2000, 1, 1))]:
        db.session.add(MemberPass(member_id=member['id'], name=name, remaining_count=count,
                                 is_active=active, valid_until=until))
    db.session.commit()
    found = client.get('/api/members/lookup', headers=strict_owner_session['headers'],
                       query_string={'phone': '13800000000'})
    assert found.status_code == 200, found.get_json()
    assert [(row['name'], row['remaining_count']) for row in found.get_json()['data']['passes']] == [('eligible', 3)]


def test_member_events_reach_authenticated_members_audience(app, client, strict_owner_session):
    # A wrong event name/audience or missing emission leaves connected member views stale.
    from app.extensions import socketio
    socket = socketio.test_client(app, flask_test_client=client,
                                 auth={'token': strict_owner_session['login']['access_token']})
    assert socket.is_connected()
    socket.get_received()
    headers = strict_owner_session['headers']
    first = post_open(client, strict_owner_session, opening())
    assert first.status_code == 201, first.get_json()
    member_id = first.get_json()['data']['member']['id']
    events = [row for row in socket.get_received() if row['name'] == 'member.changed']
    assert events and events[0]['args'][0]['member_id'] == member_id
    assert bind(client, strict_owner_session, member_id).status_code == 200
    assert any(row['name'] == 'member.changed' for row in socket.get_received())
    # Zero-balance legacy account can be archived after binding.
    member = client.post('/api/members', headers=headers, json={'phone': '13900000000'}).get_json()['data']
    assert bind(client, strict_owner_session, member['id'], card_uid='0099', idempotency_key='bind-empty').status_code == 200
    socket.get_received()
    assert client.delete(f"/api/members/{member['id']}", headers=headers,
                         json={'password': strict_owner_session['password']}).status_code == 200
    assert any(row['name'] == 'member.changed' for row in socket.get_received())
    socket.disconnect()


def test_disabled_member_is_not_identified_by_phone_or_card(client, strict_owner_session):
    # Card activation alone cannot bypass the underlying account's enabled state.
    first = post_open(client, strict_owner_session, opening(phone='13800000000'))
    assert first.status_code == 201
    member = Member.query.one()
    member.is_active = False
    db.session.commit()
    for query in ({'phone': '13800000000'}, {'card_uid': '000315346091'}):
        found = client.get('/api/members/lookup', headers=strict_owner_session['headers'], query_string=query)
        assert found.status_code == 404, found.get_json()
        assert found.get_json()['error']['code'] == 'MEMBER_NOT_FOUND'


def test_new_period_cannot_identify_or_replay_old_members(client, strict_owner_session):
    # Period scope must apply to UID, phone and financial retry records alike.
    from app.models import BusinessPeriod, BusinessStateModel
    from app.business_period import archive_read
    original = post_open(client, strict_owner_session, opening(phone='13800000000'))
    assert original.status_code == 201
    old_period = db.session.get(BusinessStateModel, 1).period_id
    new_period = BusinessPeriod()
    db.session.add(new_period)
    db.session.flush()
    db.session.get(BusinessStateModel, 1).period_id = new_period.id
    db.session.commit()
    login = client.post('/api/auth/login', json={'username': 'fixture-owner',
        'password': strict_owner_session['password'], 'client_channel': 'desktop',
        'terminal_code': strict_owner_session['terminal_code']})
    assert login.status_code == 200, login.get_json()
    fresh = {**strict_owner_session, 'headers': {'Authorization': 'Bearer ' + login.get_json()['data']['access_token'],
                                                'X-Business-Period': new_period.id}}
    for query, code in [({'phone': '13800000000'}, 'MEMBER_NOT_FOUND'),
                        ({'card_uid': '000315346091'}, 'CARD_NOT_FOUND')]:
        found = client.get('/api/members/lookup', headers=fresh['headers'], query_string=query)
        assert found.status_code == 404, found.get_json()
        assert found.get_json()['error']['code'] == code
    recreated = post_open(client, fresh, opening(phone='13800000000'))
    assert recreated.status_code == 201, recreated.get_json()
    assert recreated.get_json()['data']['member']['id'] != original.get_json()['data']['member']['id']
    with archive_read(old_period):
        assert Member.query.one().balance == Decimal('100.00')
        assert StoredValueLedger.query.count() == MemberCardBinding.query.count() == 1
