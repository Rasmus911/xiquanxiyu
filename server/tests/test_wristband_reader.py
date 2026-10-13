import pytest

from app.extensions import db
from app.models import AuditLog, Wristband


def band(number):
    return Wristband.query.filter_by(number=number, is_active=True).one()


def bind(client, session, number='001', uid='000315346091', version=0, password=None):
    body = {'chip_uid': uid, 'version': version}
    if password is not None:
        body['password'] = password
    return client.put('/api/wristband-reader/bindings/' + band(number).id,
                      headers=session['headers'], json=body)


def test_owner_can_list_hundred_and_bind_leading_zeros(client, formal_catalog, strict_owner_session):
    listed = client.get('/api/wristband-reader/bindings', headers=strict_owner_session['headers'])
    assert listed.status_code == 200
    assert len(listed.json['data']) == 100
    assert {row['number'] for row in listed.json['data']} == {f'{n:03}' for n in range(1, 101)}
    response = bind(client, strict_owner_session)
    assert response.status_code == 200, response.json
    assert response.json['data']['chip_uid'] == '000315346091'
    assert response.json['data']['version'] == 1
    assert bind(client, strict_owner_session, version=1).status_code == 200
    assert AuditLog.query.filter_by(action='wristband.chip_bind').count() == 1
    from app.serializers import ACTION_LABELS
    assert ACTION_LABELS.get('wristband.chip_bind') == '录入或更换手牌芯片'


@pytest.mark.parametrize('role,allowed', [('cashier', True), ('inventory', False),
    ('manager', False), ('male_scrubber', False), ('female_scrubber', False), ('floor_attendant', False)])
def test_binding_role_and_navigation(client, formal_catalog, desktop050_employee_session, role, allowed):
    session = desktop050_employee_session(role=role)
    state = session['login']['business_state']
    assert state['capabilities'].get('wristband_bind', False) is allowed
    assert ('wristband-bindings' in state['ui_pages']) is allowed
    assert bind(client, session).status_code == (200 if allowed else 403)


def test_duplicate_uid_cannot_change_other_band(client, formal_catalog, strict_owner_session):
    assert bind(client, strict_owner_session).status_code == 200
    response = bind(client, strict_owner_session, number='051')
    assert response.status_code == 409
    assert response.json['error']['code'] == 'CHIP_ALREADY_BOUND'


@pytest.mark.parametrize('uid', ['', 'abc', '1e12', '１２３', '1' * 65, 315346091, '12 34'])
def test_invalid_uid(client, formal_catalog, strict_owner_session, uid):
    assert bind(client, strict_owner_session, uid=uid).status_code == 400


def test_replace_and_unbind_require_own_password_and_exact_version(client, formal_catalog, strict_owner_session):
    assert bind(client, strict_owner_session).status_code == 200
    assert bind(client, strict_owner_session, uid='12345678', version=0,
                password=strict_owner_session['password']).status_code == 409
    assert bind(client, strict_owner_session, uid='12345678', version=1,
                password='incorrect-password').status_code == 403
    replaced = bind(client, strict_owner_session, uid='12345678', version=1,
                    password=strict_owner_session['password'])
    assert replaced.status_code == 200
    assert replaced.json['data']['version'] == 2
    url = '/api/wristband-reader/bindings/' + band('001').id
    assert client.delete(url, headers=strict_owner_session['headers'],
                         json={'version': 2, 'password': 'incorrect-password'}).status_code == 403
    deleted = client.delete(url, headers=strict_owner_session['headers'],
        json={'version': 2, 'password': strict_owner_session['password']})
    assert deleted.status_code == 200
    assert deleted.json['data']['chip_uid'] is None
    # Tombstone version survives unbinding: stale first-bind cannot overwrite.
    assert deleted.json['data']['version'] == 3
    assert bind(client, strict_owner_session, version=0).status_code == 409


def test_busy_band_and_retired_band_cannot_be_bound(client, formal_catalog, strict_owner_session):
    current = band('001')
    current.status = 'in_use'
    db.session.commit()
    assert bind(client, strict_owner_session).status_code == 409
    old = Wristband.query.filter_by(number='8001').one()
    assert client.put('/api/wristband-reader/bindings/' + old.id,
        headers=strict_owner_session['headers'], json={'chip_uid': '12345678', 'version': 0}).status_code == 409


def test_only_the_current_hundred_numbers_can_be_bound(client, formal_catalog, strict_owner_session):
    extra = Wristband(number='101', bath_area='female')
    db.session.add(extra)
    db.session.commit()
    rows = client.get('/api/wristband-reader/bindings', headers=strict_owner_session['headers']).json['data']
    assert len(rows) == 100
    assert client.put('/api/wristband-reader/bindings/' + extra.id, headers=strict_owner_session['headers'],
        json={'chip_uid': '12345678', 'version': 0}).status_code == 409


def test_mobile_highest_cannot_bind_or_open(client, formal_catalog, strict_owner_session):
    logged = client.post('/api/auth/login', json={'username': 'fixture-a',
        'password': strict_owner_session['password'], 'client_channel': 'mobile',
        'terminal_code': strict_owner_session['terminal_code']})
    assert logged.status_code == 200
    data = logged.json['data']
    assert data['business_state']['capabilities'].get('wristband_bind', False) is False
    headers = {'Authorization': 'Bearer ' + data['access_token'],
               'X-Business-Period': data['business_state']['period_id']}
    assert client.get('/api/wristband-reader/bindings', headers=headers).status_code == 403
    assert client.post('/api/wristband-reader/scan', headers=headers,
        json={'chip_uid': '12345678', 'link_mode': False, 'idempotency_key': 'test-mobile'}).status_code == 403
