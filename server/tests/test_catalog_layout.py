import pytest

from app.extensions import db
from app.models import CatalogItem, Employee


def test_layout_compare_and_swap_and_global_mixed_order(client, strict_owner_session):
    headers = strict_owner_session['headers']
    before = client.get('/api/catalog/layout', headers=headers)
    assert before.status_code == 200
    before = before.get_json()['data']
    expected = {item.id for item in CatalogItem.query.filter(CatalogItem.is_active.is_(True), CatalogItem.kind.in_(['service', 'product'])).all()}
    assert set(before['ids']) == expected
    payload = {'revision': before['revision'], 'ids': list(reversed(before['ids']))}
    saved = client.put('/api/catalog/layout', headers=headers, json=payload)
    assert saved.status_code == 200
    assert saved.get_json()['data']['ids'] == payload['ids']
    rows = client.get('/api/catalog?active=true', headers=headers).get_json()['data']
    assert [item['id'] for item in rows if item['kind'] in ('service', 'product')] == payload['ids']
    assert client.put('/api/catalog/layout', headers=headers, json=payload).status_code == 409


@pytest.mark.parametrize('bad', ['duplicate', 'missing', 'ticket', 'external', 'revision_bool'])
def test_bad_layout_is_atomic(client, strict_owner_session, bad):
    headers = strict_owner_session['headers']
    result = client.get('/api/catalog/layout', headers=headers)
    assert result.status_code == 200
    before = result.get_json()['data']
    payload = {'revision': before['revision'], 'ids': list(before['ids'])}
    if bad == 'duplicate': payload['ids'].append(payload['ids'][0])
    if bad == 'missing': payload['ids'].pop()
    if bad == 'ticket': payload['ids'][0] = CatalogItem.query.filter_by(kind='ticket').first().id
    if bad == 'external': payload['ids'][0] = 'not-an-item'
    if bad == 'revision_bool': payload['revision'] = True
    assert client.put('/api/catalog/layout', headers=headers, json=payload).status_code == 409
    assert client.get('/api/catalog/layout', headers=headers).get_json()['data'] == before


@pytest.mark.parametrize('role', ['male_scrubber', 'floor_attendant', 'manager'])
def test_unbound_staff_cannot_rearrange_even_when_catalog_write_is_allowed(client, strict_owner_session, role):
    created = client.post('/api/employees', headers=strict_owner_session['headers'], json={'username': role,
        'display_name': role, 'role': role, 'password': 'fixture-only-2026', 'allowed_channels': ['desktop'], 'is_active': True})
    assert created.status_code == 201
    login = client.post('/api/auth/login', json={'username': role, 'password': 'fixture-only-2026',
        'terminal_code': 'ENTRY-TEST', 'client_channel': 'desktop'}).get_json()['data']
    headers = {'Authorization': 'Bearer ' + login['access_token'], 'X-Business-Period': login['business_state']['period_id']}
    assert client.get('/api/catalog/layout', headers=headers).status_code == 403
    assert client.put('/api/catalog/layout', headers=headers, json={'revision': 1, 'ids': []}).status_code == 403


def test_bound_mobile_admin_can_rearrange_and_change_prices(client, strict_owner_session):
    row = db.session.get(Employee, strict_owner_session['administrator_ids'][0])
    login = client.post('/api/auth/login', json={'username': row.username, 'password': strict_owner_session['password'],
        'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'}).get_json()['data']
    assert 'catalog:layout' in login['permissions']
    assert 'catalog:write' in login['permissions']
    headers = {'Authorization': 'Bearer ' + login['access_token'], 'X-Business-Period': login['business_state']['period_id']}
    result = client.get('/api/catalog/layout', headers=headers)
    assert result.status_code == 200
    before = result.get_json()['data']
    assert client.put('/api/catalog/layout', headers=headers, json=before).status_code == 200
    assert client.patch('/api/catalog/' + before['ids'][0], headers=headers, json={'price': 0}).status_code == 200


def test_catalog_membership_change_invalidates_an_open_layout(client, strict_owner_session):
    headers = strict_owner_session['headers']
    before = client.get('/api/catalog/layout', headers=headers)
    assert before.status_code == 200
    before = before.get_json()['data']
    response = client.post('/api/catalog', headers=headers, json={'kind': 'product', 'name': '新饮品', 'price': '3', 'stock_tracked': True})
    assert response.status_code == 201
    after = client.get('/api/catalog/layout', headers=headers).get_json()['data']
    assert after['revision'] > before['revision']
    assert response.get_json()['data']['id'] in after['ids']
    assert client.put('/api/catalog/layout', headers=headers, json=before).status_code == 409
