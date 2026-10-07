from decimal import Decimal

import pytest

from app.extensions import db
from app.models import CatalogItem, OrderItem, Visit


@pytest.mark.parametrize('channel', ['desktop', 'mobile'])
def test_stale_order_version_writes_nothing_and_replay_returns_original(client, admin_session, channel):
    headers = dict(admin_session['headers'])
    bands = client.get('/api/wristbands', headers=headers).get_json()['data']
    opened = client.post('/api/wristbands/' + bands[0]['id'] + '/open', headers=headers, json={})
    assert opened.status_code in (200, 201)
    visit_id = opened.get_json()['data']['id']
    visit = db.session.get(Visit, visit_id)
    product = CatalogItem.query.filter_by(kind='product', stock_tracked=True).first()
    stock = Decimal(product.stock_quantity)
    count = OrderItem.query.count()
    endpoint = f'/api/visits/{visit_id}/items/batch' if channel == 'desktop' else f'/api/mobile/visits/{visit_id}/items'
    # A genuine mobile session, not an untrusted X-Client-Type override.
    if channel == 'mobile':
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123',
            'terminal_code': 'TEST-01', 'client_channel': 'mobile'})
        headers = {'Authorization': 'Bearer ' + response.get_json()['data']['access_token']}
    headers['Idempotency-Key'] = 'stale-order'
    items = [{'catalog_item_id': product.id, 'quantity': 2}]
    stale = client.post(endpoint, headers=headers, json={'version': visit.version - 1, 'items': items})
    assert stale.status_code == 409
    assert stale.get_json()['error']['code'] == 'VISIT_VERSION_CONFLICT'
    assert OrderItem.query.count() == count
    assert Decimal(product.stock_quantity) == stock
    headers['Idempotency-Key'] = 'valid-order'
    body = {'version': visit.version, 'items': items}
    saved = client.post(endpoint, headers=headers, json=body)
    assert saved.status_code == 201
    assert client.post(endpoint, headers=headers, json=body).status_code in (200, 201)
    assert OrderItem.query.count() == count + 1
    assert Decimal(product.stock_quantity) == stock - 2
