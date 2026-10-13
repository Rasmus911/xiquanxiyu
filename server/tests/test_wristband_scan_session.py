import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models import OrderItem, Visit, Wristband
from test_wristband_reader import band, bind


@pytest.fixture
def scanner(client, formal_catalog, strict_owner_session):
    for number in ('001', '002', '003', '051'):
        assert bind(client, strict_owner_session, number=number, uid='12345' + number).status_code == 200

    def send(number='001', link=False, session=None, key=None, headers=None, extra=None):
        body = {'chip_uid': '12345' + number, 'link_mode': link, 'idempotency_key': key or str(uuid.uuid4())}
        if session:
            body['session_id'] = session
        body.update(extra or {})
        return client.post('/api/wristband-reader/scan', headers=headers or strict_owner_session['headers'], json=body)
    return send


def test_scan_opens_exactly_one_authoritative_ticket_and_replays(scanner):
    response = scanner(key='exact-replay-key')
    assert response.status_code == 200, response.json
    result = response.json['data']
    assert result['opened'] is True
    assert result['wristband_number'] == '001'
    assert result['session'] is None
    replay = scanner(key='exact-replay-key')
    assert replay.json['data'] == result
    repeat = scanner()
    assert repeat.json['data']['opened'] is False
    visits = Visit.query.filter_by(wristband_id=band('001').id).all()
    assert len(visits) == 1
    tickets = OrderItem.query.filter_by(visit_id=visits[0].id).all()
    assert len(tickets) == 1
    assert str(tickets[0].total_amount) == '15.00'
    assert scanner('002', key='exact-replay-key').status_code == 409


def test_server_sliding_59_seconds_and_exact_60_boundary(scanner, monkeypatch):
    import app.wristband_reader_service as service
    now = datetime(2026, 10, 13, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(service, 'utcnow', lambda: now)
    first = scanner(link=True).json['data']['session']
    now += timedelta(seconds=59)
    second = scanner('051', link=True, session=first['id']).json['data']['session']
    assert second['id'] == first['id']
    assert second['numbers'] == ['001', '051']
    assert second['expires_at'] != first['expires_at']
    # Duplicate and unknown scans must not slide the window.
    now += timedelta(seconds=10)
    duplicate = scanner(link=True, session=second['id']).json['data']
    assert duplicate['opened'] is False
    assert duplicate['session']['expires_at'] == second['expires_at']
    assert scanner('099', link=True, session=second['id']).status_code == 404
    now += timedelta(seconds=50)
    third = scanner('002', link=True, session=second['id']).json['data']['session']
    assert third['id'] != second['id']
    assert third['numbers'] == ['002']
    assert Visit.query.filter_by(wristband_id=band('001').id).one().party_id == Visit.query.filter_by(wristband_id=band('051').id).one().party_id


@pytest.mark.parametrize('change', ['closed', 'party', 'version', 'wristband'])
def test_group_business_changes_end_scan_window(scanner, change):
    first = scanner(link=True).json['data']['session']
    visit = Visit.query.filter_by(wristband_id=band('001').id).one()
    if change == 'closed':
        visit.status = 'closed'
    elif change == 'party':
        visit.party_id = str(uuid.uuid4())
    elif change == 'version':
        visit.version += 1
    else:
        visit.wristband_id = band('003').id
    db.session.commit()
    second = scanner('051', link=True, session=first['id']).json['data']['session']
    assert second['id'] != first['id']
    assert second['numbers'] == ['051']


def test_other_account_cannot_adopt_scan_session(scanner, desktop050_employee_session):
    first = scanner(link=True).json['data']['session']
    cashier = desktop050_employee_session()
    assert scanner('051', link=True, session=first['id'], headers=cashier['headers']).status_code == 403
    assert band('051').status == 'available'


def test_new_login_same_user_terminal_cannot_resume_previous_page_session(scanner, client, strict_owner_session):
    first=scanner(link=True).json['data']['session']
    login=client.post('/api/auth/login',json={'username':'fixture-owner','password':strict_owner_session['password'],
        'client_channel':'desktop','terminal_code':strict_owner_session['terminal_code']})
    assert login.status_code==200
    data=login.json['data']
    headers={'Authorization':'Bearer '+data['access_token'],'X-Business-Period':data['business_state']['period_id']}
    assert scanner('051',link=True,session=first['id'],headers=headers).status_code==403


def test_busy_or_retired_and_client_amount_are_rejected(scanner):
    row = band('001')
    row.status = 'lost'
    db.session.commit()
    assert scanner().status_code == 409
    row.status = 'available'
    row.is_active = False
    db.session.commit()
    assert scanner().status_code == 409
    assert scanner('051', extra={'ticket_price': 0}).status_code == 400


def test_queue_replay_after_closed_visit_does_not_reopen(scanner):
    result = scanner(key='lost-response-request').json['data']
    visit = db.session.get(Visit, result['visit_id'])
    visit.status = 'closed'
    band('001').status = 'available'
    db.session.commit()
    assert scanner(key='lost-response-request').json['data'] == result
    assert Visit.query.filter_by(wristband_id=band('001').id).count() == 1


def test_unrelated_active_wristband_never_joins_new_group(scanner):
    independent = scanner('051').json['data']
    first = scanner(link=True).json['data']['session']
    repeated = scanner('051', link=True, session=first['id']).json['data']
    assert repeated['opened'] is False
    assert repeated['session']['numbers'] == ['001']
    assert db.session.get(Visit, independent['visit_id']).party_id is None
