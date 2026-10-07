"""0.4.7 observable stock costs and automatic alert behavior."""
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.extensions import db
from app.models import AuditLog, StockMovement


def post(client, headers, path, body, key):
    return client.post(path, headers={**headers, 'Idempotency-Key': key}, json=body)


def create(client, headers, **extra):
    response = post(client, headers, '/api/inventory/stock-items', {
        'name': '成本测试奶浴', 'base_unit': '袋', 'package_unit': '箱',
        'units_per_package': '200', 'opening_quantity': '4', 'opening_unit': 'package', **extra,
    }, 'cost-opening')
    assert response.status_code == 201, response.get_json()
    return response.get_json()['data']


def test_opening_alert_is_fifteen_percent_in_base_units(client, admin_session):
    item = create(client, admin_session['headers'], low_stock_threshold='1')
    assert item['stock_quantity'] == '800.000'
    assert item['low_stock_threshold'] == '120.000'


def test_purchase_records_cost_and_alert_without_double_receiving(client, admin_session):
    h = admin_session['headers']; item = create(client, h)
    body = {'stock_item_id': item['id'], 'version': item['version'], 'movement_type': 'purchase',
            'quantity': '4', 'input_unit': 'package', 'reason': '采购入库', 'unit_cost': '120'}
    r = post(client, h, '/api/inventory/stock-adjust', body, 'cost-purchase')
    assert r.status_code == 200, r.get_json()
    result = r.get_json()['data']
    assert result['stock_item']['stock_quantity'] == '1600.000'
    assert result['stock_item']['low_stock_threshold'] == '120.000'
    assert result['movement']['cost']['unit_cost'] == '120.00'
    assert result['movement']['cost']['total_cost'] == '480.00'
    assert result['movement']['cost']['base_unit_cost'] == '0.600000'
    assert post(client, h, '/api/inventory/stock-adjust', body, 'cost-purchase').get_json()['data'] == result
    assert StockMovement.query.filter_by(stock_item_id=item['id'], movement_type='purchase').count() == 1


def test_cost_can_be_added_later_with_history_version_and_audit(client, admin_session):
    h = admin_session['headers']; item = create(client, h)
    movement = client.get('/api/inventory/stock-movements', headers=h).get_json()['data'][0]
    assert movement['cost'] is None
    path = '/api/inventory/stock-movements/' + movement['id'] + '/cost'
    r = post(client, h, path, {'expected_cost_id': None, 'unit_cost': '120'}, 'add-cost')
    assert r.status_code == 200, r.get_json()
    cost = r.get_json()['data']['cost']
    assert cost['total_cost'] == '480.00'
    assert post(client, h, path, {'expected_cost_id': None, 'unit_cost': '100'}, 'stale-cost').status_code == 409
    changed = post(client, h, path, {'expected_cost_id': cost['id'], 'unit_cost': '100', 'password':'admin123'}, 'amend-cost')
    assert changed.status_code == 200
    assert changed.get_json()['data']['cost']['total_cost'] == '400.00'
    events = AuditLog.query.filter_by(action='stock.cost').order_by(AuditLog.chain_index).all()
    assert events[-1].details['before']['total_cost'] == '480.00'
    assert events[-1].details['after']['total_cost'] == '400.00'
    assert StockMovement.query.filter_by(stock_item_id=item['id']).one().quantity == Decimal('800')
    with pytest.raises(DatabaseError):
        db.session.connection().execute(text('UPDATE stock_costs SET unit_cost=1'))
    db.session.rollback()


@pytest.mark.parametrize('value', ['-1', 'NaN', 'Infinity', '0.001', '10000000000', True])
def test_invalid_cost_rejects_entire_receipt(client, admin_session, value):
    h = admin_session['headers']; item = create(client, h)
    r = post(client, h, '/api/inventory/stock-adjust', {'stock_item_id': item['id'],
        'version': item['version'], 'movement_type': 'purchase', 'quantity': '4',
        'input_unit': 'package', 'reason': '采购入库', 'unit_cost': value}, 'invalid-cost')
    assert r.status_code == 400
    assert r.get_json()['error']['code'] == 'INVALID_STOCK_COST'
    assert StockMovement.query.filter_by(stock_item_id=item['id']).count() == 1


def test_return_does_not_rebase_warning_or_accept_purchase_cost(client, admin_session):
    h = admin_session['headers']; item = create(client, h)
    r = post(client, h, '/api/inventory/stock-adjust', {'stock_item_id': item['id'],
        'version': item['version'], 'movement_type': 'return', 'quantity': '1',
        'input_unit': 'base', 'reason': '误出库退回'}, 'return')
    assert r.status_code == 200
    assert r.get_json()['data']['stock_item']['low_stock_threshold'] == '120.000'
