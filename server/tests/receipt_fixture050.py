"""Real, scoped API ordering and checkout for receipt regression tests."""
from app.extensions import db
from app.models import CatalogItem, Visit, Wristband


def order(client, owner, factory, role='male_scrubber', area='male', key='isolated-order'):
    worker = factory(role)
    band = Wristband.query.filter_by(number='8001' if area == 'male' else '9001').one()
    opened = client.post('/api/wristbands/' + band.id + '/open', headers=owner['headers'], json={})
    assert opened.status_code == 201
    visit = db.session.get(Visit, opened.get_json()['data']['id'])
    catalog = CatalogItem.query.filter_by(kind='service', is_active=True,
        mobile_scope='rest' if role == 'floor_attendant' else 'scrub').first()
    payload = {'version':visit.version,'items':[{'catalog_item_id':catalog.id,'quantity':1,
        'inventory_mode':'manual','inventory_consumption':[]}]}
    headers = {**worker['headers'],'Idempotency-Key':key}
    path = '/api/visits/' + visit.id + '/items/batch'
    response = client.post(path,headers=headers,json=payload)
    assert response.status_code == 201, response.get_json()
    return {'worker':worker,'visit':visit,'catalog':catalog,'path':path,'headers':headers,
            'body':payload,'response':response.get_json()}


def settle(client, owner, visit):
    from app.models import OrderItem
    from decimal import Decimal
    total = sum((r.total_amount for r in OrderItem.query.filter_by(visit_id=visit.id,status='active')),Decimal(0))
    result = client.post('/api/checkout',headers=owner['headers'],json={'visit_ids':[visit.id],
        'payments':[{'method':'cash','amount':str(total)}], 'idempotency_key':'isolated-checkout'})
    assert result.status_code == 201, result.get_json()
    return result.get_json()['data']['id']
