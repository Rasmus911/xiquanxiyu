"""Mobile stock and protected admin entry regressions use isolated UUID bindings."""
import json

from app.extensions import db, socketio
from app.models import CatalogItem, Employee


def create_stock(client, session):
    response = client.post('/api/employees', headers=session['headers'], json={
        'username': 'fixture-stock', 'display_name': '库管', 'role': 'inventory',
        'password': 'fixture-stock-2026', 'allowed_channels': ['mobile'], 'is_active': True})
    assert response.status_code == 201
    login = client.post('/api/auth/login', json={'username': 'fixture-stock', 'password': 'fixture-stock-2026',
        'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'})
    assert login.status_code == 200
    data = login.get_json()['data']
    return response.get_json()['data']['id'], data, {'Authorization': 'Bearer ' + data['access_token'],
        'X-Business-Period': data['business_state']['period_id']}


def test_inventory_mobile_can_order_add_stock_and_read_reports(client, strict_owner_session):
    _, _, headers = create_stock(client, strict_owner_session)
    response = client.get('/api/mobile/bootstrap', headers=headers)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['wristbands'] == [] and data['catalog']
    assert data['employee']['capabilities']['orders_view'] is True
    assert data['employee']['capabilities']['reports_view'] is True
    assert data['employee']['capabilities']['inventory_manage'] is True
    response = client.get('/api/mobile/management/inventory', headers=headers)
    assert response.status_code == 200
    product = response.get_json()['data'][0]
    before = db.session.get(CatalogItem, product['id']).stock_quantity
    response = client.post('/api/mobile/management/inventory/add',
        headers={**headers, 'Idempotency-Key': 'fixture-stock-add'},
        json={'catalog_item_id': product['id'], 'quantity': 2})
    assert response.status_code == 201
    assert db.session.get(CatalogItem, product['id']).stock_quantity == before + 2
    assert client.get('/api/mobile/management/report', headers=headers).status_code == 200
    assert client.post('/api/mobile/visits/not-a-visit/items', headers={**headers, 'Idempotency-Key':'missing'}, json={}).status_code == 404


def test_revoking_mobile_entry_disconnects_only_target_not_owner(app, client, strict_owner_session):
    employee_id, data, headers = create_stock(client, strict_owner_session)
    target_socket = socketio.test_client(app, auth={'token': data['access_token']})
    owner_socket = socketio.test_client(app, auth={'token': strict_owner_session['login']['access_token']})
    assert target_socket.is_connected() and owner_socket.is_connected()
    response = client.patch('/api/employees/' + employee_id, headers=strict_owner_session['headers'],
        json={'allowed_channels': ['desktop']})
    assert response.status_code == 200
    assert not target_socket.is_connected()
    assert owner_socket.is_connected()
    assert client.get('/api/mobile/bootstrap', headers=headers).status_code == 401
    owner_socket.disconnect()


def test_bound_mobile_administrators_can_use_every_existing_mobile_module(client, strict_owner_session):
    for employee_id in strict_owner_session['administrator_ids']:
        employee = db.session.get(Employee, employee_id)
        response = client.post('/api/auth/login', json={'username': employee.username,
            'password': strict_owner_session['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'})
        assert response.status_code == 200
        data = response.get_json()['data']
        headers = {'Authorization': 'Bearer ' + data['access_token'], 'X-Business-Period': data['business_state']['period_id']}
        response = client.get('/api/mobile/bootstrap', headers=headers)
        assert response.status_code == 200
        assert all(response.get_json()['data']['employee']['capabilities'].values())
        assert client.get('/api/mobile/management/report', headers=headers).status_code == 200
        assert client.get('/api/mobile/management/inventory', headers=headers).status_code == 200


def test_channel_diagnostics_are_read_only_and_expose_no_credential(app, strict_owner_session):
    ids = strict_owner_session['administrator_ids']
    before = {row.id: (row.password_hash, row.session_version, row.allowed_channels) for row in Employee.query.all()}
    args = ['access-policy', 'check-channels', '--terminal-code', 'ENTRY-TEST']
    for employee_id in ids:
        args += ['--employee-id', employee_id]
    result = app.test_cli_runner().invoke(args=args)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data['terminal']['is_active'] is True
    assert [row['id'] for row in data['employees']] == ids
    assert all(row['channels']['mobile']['allowed'] for row in data['employees'])
    assert strict_owner_session['password'] not in result.output
    assert 'password_hash' not in result.output and 'access_token' not in result.output
    assert {row.id: (row.password_hash, row.session_version, row.allowed_channels) for row in Employee.query.all()} == before
