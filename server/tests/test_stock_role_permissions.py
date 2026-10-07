import pytest
from app.extensions import db
from app.models import Employee
from app.auth_service import hash_password


@pytest.mark.parametrize('role', ['cashier', 'inventory'])
def test_six_modules_without_sensitive_authority(client, strict_owner_session, role):
    owner = strict_owner_session
    r = client.post('/api/employees', headers=owner['headers'], json={'username': 'five-' + role,
        'display_name': role, 'role': role, 'password': 'fixture-five-2026', 'allowed_channels': ['desktop']})
    assert r.status_code == 201
    login = client.post('/api/auth/login', json={'username': 'five-' + role, 'password': 'fixture-five-2026',
        'terminal_code': 'ENTRY-TEST', 'client_channel': 'desktop'}).get_json()['data']
    assert set(login['business_state']['ui_pages']) == {'wristbands', 'members', 'print-jobs', 'catalog', 'inventory', 'reports'}
    h = {'Authorization': 'Bearer ' + login['access_token'], 'X-Business-Period': login['business_state']['period_id']}
    for path in ('/api/wristbands', '/api/members', '/api/catalog', '/api/inventory/stock-items'):
        assert client.get(path, headers=h).status_code == 200
    assert client.post('/api/catalog', headers=h, json={'kind': 'service', 'name': '新服务', 'price': '12'}).status_code == 201
    for kind in ('ticket','compensation'):
        assert client.post('/api/catalog',headers=h,json={'kind':kind,'name':'可修改项目','price':'1'}).status_code == 201
    assert client.post('/api/catalog',headers=h,json={'kind':'package','name':'缺少定义','price':'1'}).status_code == 400
    rows = client.get('/api/catalog',headers=h).get_json()['data']
    assert all(row['can_edit'] for row in rows)
    ticket = next(row for row in rows if row['kind']=='ticket')
    assert client.patch('/api/catalog/'+ticket['id'],headers=h,json={'price':'0'}).status_code == 200
    for path in ('/api/reports/summary', '/api/reports/trend', '/api/reports/insights', '/api/mobile/management/report'):
        assert client.get(path, headers=h).status_code == 200
    for path in ('/api/audit', '/api/employees', '/api/settings'):
        assert client.get(path, headers=h).status_code == 403
    assert client.post('/api/checkout/anything/refund', headers=h, json={}).status_code == 403
    assert client.get('/api/business/reset/preview', headers=h).status_code == 403
