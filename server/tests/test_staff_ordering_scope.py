"""A scoped staff account cannot bypass bath/catalog filters via desktop or mobile APIs."""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import CatalogItem, Employee, OrderItem, Visit, Wristband


@pytest.mark.parametrize('role,area,want', [
    ('male_scrubber', 'male', True), ('male_scrubber', 'female', False),
    ('female_scrubber', 'male', False), ('female_scrubber', 'female', True),
    ('floor_attendant', 'male', True), ('floor_attendant', 'female', True),
    ('unknown', 'male', False),
])
def test_object_scope_does_not_infer_authority_from_channel_or_area_input(app, role, area, want):
    from app.ordering_scope import can_read_visit
    employee = Employee(role=role)
    band = Wristband(number='001' if area == 'male' else '051', bath_area=area, is_active=True,status='in_use')
    assert can_read_visit(employee, band, Visit(status='open')) is want
    assert can_read_visit(employee, band, Visit(status='closed')) is False
    band.status = 'idle'
    assert can_read_visit(employee, band, Visit(status='open')) is False
    band.status='in_use'; band.is_active=False
    assert can_read_visit(employee,band,Visit(status='open')) is False


@pytest.fixture()
def linked_scope(client, strict_owner_session):
    headers = strict_owner_session['headers']
    bands = client.get('/api/wristbands', headers=headers).get_json()['data']
    ids = [next(row['id'] for row in bands if row['number'] == number) for number in ('8001', '9001')]
    response = client.post('/api/wristbands/link-batch', headers=headers, json={'wristband_ids': ids})
    assert response.status_code == 200
    visits = {band.number: Visit.query.filter_by(wristband_id=band.id, status='open').one().id
              for band in Wristband.query.filter(Wristband.id.in_(ids)).all()}
    catalog = client.get('/api/catalog', headers=headers).get_json()['data']
    return {'owner': strict_owner_session, 'visits': visits,
        'scrub': next(row['id'] for row in catalog if row['name'] == '一次性搓澡巾'),
        'rest': next(row['id'] for row in catalog if row['name'] == '矿泉水')}


def staff_login(client, linked_scope, role, channel='desktop'):
    response = client.post('/api/employees', headers=linked_scope['owner']['headers'], json={
        'username': role, 'display_name': '测试岗位', 'role': role, 'password': 'fixture-staff-2026',
        'allowed_channels': ['desktop'] if role == 'cashier' else ['desktop', 'mobile'], 'is_active': True})
    assert response.status_code == 201
    login = client.post('/api/auth/login', json={'username': role, 'password': 'fixture-staff-2026',
        'terminal_code': 'ENTRY-TEST', 'client_channel': channel})
    assert login.status_code == 200
    data = login.get_json()['data']
    return {'Authorization': 'Bearer ' + data['access_token'], 'X-Business-Period': data['business_state']['period_id']}


@pytest.mark.parametrize('role,numbers', [('male_scrubber', ['8001']), ('female_scrubber', ['9001']),
                                        ('floor_attendant', ['8001', '9001'])])
def test_desktop_staff_only_reads_active_allowed_bands_and_linked_members(client, linked_scope, role, numbers):
    headers = staff_login(client, linked_scope, role)
    response = client.get('/api/wristbands', headers=headers)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert [row['number'] for row in data] == numbers
    for row in data:
        assert row['linked_numbers'] == numbers
        assert set(row['linked_visit_ids']) == {linked_scope['visits'][number] for number in numbers}
    detail = client.get('/api/visits/' + linked_scope['visits'][numbers[0]], headers=headers)
    assert detail.status_code == 200
    assert [row['wristband_number'] for row in detail.get_json()['data']['linked_visits']] == numbers
    if len(numbers) == 1:
        forbidden = '9001' if numbers[0] == '8001' else '8001'
        assert client.get('/api/visits/' + linked_scope['visits'][forbidden], headers=headers).status_code == 403


@pytest.mark.parametrize('role,numbers,scopes', [
    ('male_scrubber', ['8001'], {'scrub', 'both'}),
    ('female_scrubber', ['9001'], {'scrub', 'both'}),
    ('floor_attendant', ['8001', '9001'], {'rest', 'both'}),
])
def test_mobile_role_is_not_elevated_just_because_it_can_order(client, linked_scope, role, numbers, scopes):
    headers = staff_login(client, linked_scope, role, 'mobile')
    response = client.get('/api/mobile/bootstrap', headers=headers)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert [row['number'] for row in data['wristbands']] == numbers
    assert {row['mobile_scope'] for row in data['catalog']} <= scopes
    assert data['employee']['capabilities']['order_all'] is False
    assert data['employee']['capabilities']['reports_view'] is False
    assert data['employee']['capabilities']['inventory_manage'] is False


def test_batch_denial_is_atomic_and_never_consumes_stock(client, linked_scope):
    headers = staff_login(client, linked_scope, 'male_scrubber')
    before = {row.id: Decimal(row.stock_quantity) for row in CatalogItem.query.all()}
    count = OrderItem.query.count()
    target = linked_scope['visits']['8001']
    response = client.post('/api/visits/' + target + '/items/batch', headers={**headers, 'Idempotency-Key': 'mixed-scope'},
        json={'items': [{'catalog_item_id': linked_scope['scrub'], 'quantity': 1},
                        {'catalog_item_id': linked_scope['rest'], 'quantity': 1}]})
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'PERMISSION_DENIED'
    assert OrderItem.query.count() == count
    assert {row.id: Decimal(row.stock_quantity) for row in CatalogItem.query.all()} == before
    for suffix in ('items', 'items/batch'):
        payload = {'catalog_item_id': linked_scope['scrub'], 'quantity': 1} if suffix == 'items' else {
            'items': [{'catalog_item_id': linked_scope['scrub'], 'quantity': 1}]}
        response = client.post('/api/visits/' + linked_scope['visits']['9001'] + '/' + suffix,
            headers={**headers, 'Idempotency-Key': 'female-' + suffix}, json=payload)
        assert response.status_code == 403
    catalog = client.get('/api/catalog?active=false', headers=headers).get_json()['data']
    assert all(row['mobile_scope'] in {'scrub', 'both'} and row['is_active'] for row in catalog)
    assert {row['kind'] for row in catalog} <= {'service', 'product'}


def test_staff_can_submit_allowed_order_but_cannot_open_void_or_collect(client, linked_scope):
    headers = staff_login(client, linked_scope, 'male_scrubber')
    target = linked_scope['visits']['8001']
    response = client.post('/api/visits/' + target + '/items/batch', headers={**headers, 'Idempotency-Key': 'allowed'},
        json={'items': [{'catalog_item_id': linked_scope['scrub'], 'quantity': 2}]})
    assert response.status_code == 201
    item_id = response.get_json()['data'][0]['id']
    assert Decimal(db.session.get(CatalogItem, linked_scope['scrub']).stock_quantity) == Decimal('8')
    assert client.post('/api/visits/' + target + '/items/' + item_id + '/void', headers=headers, json={}).status_code == 403
    assert client.post('/api/checkout', headers=headers, json={}).status_code == 403
    band = Wristband.query.filter_by(number='8002').one()
    assert client.post('/api/wristbands/' + band.id + '/open', headers=headers, json={}).status_code == 403


def test_frontdesk_and_inventory_read_full_group_without_sensitive_pages(client, linked_scope):
    cashier = staff_login(client, linked_scope, 'cashier')
    response = client.get('/api/visits/' + linked_scope['visits']['8001'], headers=cashier)
    assert response.status_code == 200
    assert len(response.get_json()['data']['linked_visits']) == 2
    stock = staff_login(client, linked_scope, 'inventory')
    assert client.get('/api/inventory', headers=stock).status_code == 200
    assert client.get('/api/catalog', headers=stock).status_code == 200
    for path in ('/api/wristbands', '/api/visits/' + linked_scope['visits']['8001']):
        assert client.get(path, headers=stock).status_code == 200
    assert client.get('/api/reports/summary', headers=stock).status_code == 200
    assert client.get('/api/settings', headers=stock).status_code == 403


def test_mobile_idempotent_replay_still_checks_the_current_bath_area(client, linked_scope):
    headers = staff_login(client, linked_scope, 'male_scrubber', 'mobile')
    target = linked_scope['visits']['8001']
    body = {'items': [{'catalog_item_id': linked_scope['scrub'], 'quantity': 1}]}
    request_headers = {**headers, 'Idempotency-Key': 'replay-after-switch'}
    assert client.post('/api/mobile/visits/' + target + '/items', headers=request_headers, json=body).status_code == 201
    band = Wristband.query.filter_by(number='8001').one()
    response = client.post('/api/wristbands/' + band.id + '/switch', headers=linked_scope['owner']['headers'],
        json={'target_number': '9002'})
    assert response.status_code == 200
    before = Decimal(db.session.get(CatalogItem, linked_scope['scrub']).stock_quantity)
    response = client.post('/api/mobile/visits/' + target + '/items', headers=request_headers, json=body)
    assert response.status_code == 403
    assert Decimal(db.session.get(CatalogItem, linked_scope['scrub']).stock_quantity) == before
