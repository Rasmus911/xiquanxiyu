"""0.5.5 orders never consume stock; real historical deductions still return."""
from decimal import Decimal
import pytest

from app.extensions import db
from app.models import Employee, OrderItem, OrderStockConsumption, StockItem, StockMovement
from app.stock_service import change_balance
from test_independent_stock import post, stock, setup_order, balance


@pytest.mark.parametrize('route', ['single', 'batch', 'mobile'])
@pytest.mark.parametrize('product', [False, True])
def test_new_orders_ignore_old_consumption_and_do_not_change_inventory(client, admin_session, route, product):
    h = admin_session['headers']
    master = stock(client, h)
    catalog, visit = setup_order(client, h, product=product)
    row = dict(catalog_item_id=catalog['id'], quantity='2', inventory_mode='manual',
               inventory_consumption=[dict(stock_item_id=master['id'], quantity='3')])
    path = '/api/visits/' + visit['id'] + '/items'
    if route == 'batch': path += '/batch'
    if route == 'mobile': path = '/api/mobile/visits/' + visit['id'] + '/items'
    response = post(client, h, path, row if route == 'single' else {'items': [row]}, 'order055')
    assert response.status_code == 201, response.get_json()
    item = response.get_json()['data'] if route == 'single' else response.get_json()['data'][0]
    assert balance(client, h, master['id'])['stock_quantity'] == '800.000'
    assert item['inventory_consumption'] == []
    assert OrderStockConsumption.query.filter_by(order_item_id=item['id']).count() == 0
    assert post(client, h, '/api/visits/' + visit['id'] + '/items/' + item['id'] + '/void', {}, 'void055').status_code == 200
    assert balance(client, h, master['id'])['stock_quantity'] == '800.000'


def test_old_client_product_order_ignores_zero_stock(client, admin_session):
    h = admin_session['headers']
    catalog, visit = setup_order(client, h, product=True)
    response = client.post('/api/visits/' + visit['id'] + '/items', headers=h,
                           json={'catalog_item_id': catalog['id'], 'quantity': '5'})
    assert response.status_code == 201, response.get_json()
    item = response.get_json()['data']
    assert item['inventory_consumption'] == []
    assert StockMovement.query.filter_by(reference_id=item['id']).count() == 0


def test_pre055_real_consumption_evidence_returns_once(client, admin_session):
    h = admin_session['headers']; master = stock(client, h)
    catalog, visit = setup_order(client, h)
    item = post(client, h, '/api/visits/' + visit['id'] + '/items',
                {'catalog_item_id': catalog['id']}, 'historical-fixture').get_json()['data']
    order = db.session.get(OrderItem, item['id'])
    order.inventory_mode = 'manual'
    employee = db.session.get(Employee, admin_session['login']['employee']['id'])
    target = db.session.get(StockItem, master['id'])
    change_balance(target, Decimal('-2'), employee, 'sale', '真实旧版本扣减证据',
                   reference_type='order_item', reference_id=order.id)
    db.session.add(OrderStockConsumption(order_item_id=order.id, stock_item_id=target.id,
        quantity=Decimal('2'), stock_name_snapshot=target.name, base_unit_snapshot=target.base_unit))
    db.session.commit()
    path = '/api/visits/' + visit['id'] + '/items/' + order.id + '/void'
    assert post(client, h, path, {}, 'old-return').status_code == 200
    assert balance(client, h, master['id'])['stock_quantity'] == '800.000'
    assert post(client, h, path, {}, 'old-return').status_code == 200
    assert balance(client, h, master['id'])['stock_quantity'] == '800.000'
