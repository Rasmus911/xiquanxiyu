"""Stock units, immutable consumption and old/new client coexistence."""
from decimal import Decimal
import pytest

from app.extensions import db
from app.models import CatalogItem, InventoryMovement, OrderItem


def post(client, headers, path, body, key):
    return client.post(path, headers={**headers, 'Idempotency-Key': key}, json=body)


def stock(client, headers, **values):
    body = {'name': '奶浴袋', 'base_unit': '袋', 'package_unit': '箱',
            'units_per_package': '200', 'opening_quantity': '4', 'opening_unit': 'package'}
    body.update(values)
    response = post(client, headers, '/api/inventory/stock-items', body, 'open-' + body['name'])
    assert response.status_code == 201, response.get_json()
    return response.get_json()['data']


def setup_order(client, headers, product=False):
    catalog = post(client, headers, '/api/catalog', {'name': '测试销售', 'kind': 'product' if product else 'service',
        'price': '20', 'mobile_scope': 'both'}, 'catalog').get_json()['data']
    band = client.get('/api/wristbands', headers=headers).get_json()['data'][0]
    visit = post(client, headers, '/api/wristbands/' + band['id'] + '/open', {}, 'visit').get_json()['data']
    return catalog, visit


def balance(client, headers, id_):
    return next(row for row in client.get('/api/inventory/stock-items?include_inactive=true', headers=headers).get_json()['data'] if row['id'] == id_)


def test_case_opening_becomes_basic_units(client, admin_session):
    item = stock(client, admin_session['headers'])
    assert item['stock_quantity'] == '800.000'
    assert item['units_per_package'] == '200.000'


def test_purchase_snapshots_conversion_and_idempotent_replay(client, admin_session):
    h = admin_session['headers']; item = stock(client, h)
    body = {'stock_item_id': item['id'], 'version': item['version'], 'movement_type': 'purchase',
            'quantity': '2', 'input_unit': 'package', 'reason': '采购'}
    response = post(client, h, '/api/inventory/stock-adjust', body, 'purchase')
    assert response.status_code == 200
    assert response.get_json()['data']['stock_item']['stock_quantity'] == '1200.000'
    assert post(client, h, '/api/inventory/stock-adjust', body, 'purchase').get_json()['data'] == response.get_json()['data']
    current = balance(client, h, item['id'])
    edited = client.patch('/api/inventory/stock-items/' + item['id'], headers={**h, 'Idempotency-Key': 'factor'},
        json={'version': current['version'], 'units_per_package': '100'})
    assert edited.status_code == 200
    assert edited.get_json()['data']['stock_quantity'] == '1200.000'
    movements = client.get('/api/inventory/stock-movements?stock_item_id=' + item['id'], headers=h).get_json()['data']
    assert next(row for row in movements if row['movement_type'] == 'purchase')['conversion_factor'] == '200.000'
    bad = client.patch('/api/inventory/stock-items/' + item['id'], headers={**h, 'Idempotency-Key': 'base'},
        json={'version': edited.get_json()['data']['version'], 'base_unit': '瓶'})
    assert bad.status_code == 409


@pytest.mark.parametrize('quantity', ['0', '-1', 'NaN', 'Infinity', '0.0001'])
def test_stock_rejects_invalid_quantities(client, admin_session, quantity):
    r = post(client, admin_session['headers'], '/api/inventory/stock-items',
        {'name': '无效', 'base_unit': '袋', 'opening_quantity': quantity}, 'invalid')
    assert r.status_code == 400


@pytest.mark.parametrize('route', ['single', 'batch', 'mobile'])
def test_manual_total_consumption_void_exactly_once(client, admin_session, route):
    h = admin_session['headers']; s = stock(client, h); c, v = setup_order(client, h)
    row = {'catalog_item_id': c['id'], 'quantity': '2', 'inventory_mode': 'manual',
           'inventory_consumption': [{'stock_item_id': s['id'], 'quantity': '1'}]}
    path = '/api/visits/' + v['id'] + '/items'
    if route == 'batch': path += '/batch'
    if route == 'mobile': path = '/api/mobile/visits/' + v['id'] + '/items'
    body = row if route == 'single' else {'items': [row]}
    response = post(client, h, path, body, 'order')
    assert response.status_code == 201, response.get_json()
    item = response.get_json()['data'] if route == 'single' else response.get_json()['data'][0]
    assert item['inventory_consumption'][0]['quantity'] == '1.000'
    assert balance(client, h, s['id'])['stock_quantity'] == '799.000'
    assert post(client, h, path, body, 'order').status_code in {200, 201}
    assert balance(client, h, s['id'])['stock_quantity'] == '799.000'
    voidpath = '/api/visits/' + v['id'] + '/items/' + item['id'] + '/void'
    assert post(client, h, voidpath, {}, 'void').status_code == 200
    assert post(client, h, voidpath, {}, 'void-other').status_code == 409
    assert balance(client, h, s['id'])['stock_quantity'] == '800.000'
    assert client.get('/api/inventory/usage', headers=h).get_json()['data'] == []


@pytest.mark.parametrize('route', ['batch', 'mobile'])
def test_aggregate_shortage_rolls_back_all_lines(client, admin_session, route):
    h = admin_session['headers']; s = stock(client, h, opening_quantity='1', opening_unit='base'); c, v = setup_order(client, h)
    row = {'catalog_item_id': c['id'], 'inventory_mode': 'manual',
           'inventory_consumption': [{'stock_item_id': s['id'], 'quantity': '0.6'}]}
    count = OrderItem.query.count()
    path = ('/api/mobile/visits/' if route == 'mobile' else '/api/visits/') + v['id'] + '/items'
    if route == 'batch': path += '/batch'
    response = post(client, h, path, {'items': [row, row]}, 'shortage')
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'INSUFFICIENT_STOCK'
    assert OrderItem.query.count() == count
    assert balance(client, h, s['id'])['stock_quantity'] == '1.000'


def test_manual_empty_product_does_not_auto_deduct_and_old_api_shares_balance(client, admin_session):
    h = admin_session['headers']; c, v = setup_order(client, h, product=True)
    assert post(client, h, '/api/inventory/adjust', {'catalog_item_id': c['id'], 'quantity': '10',
        'movement_type': 'opening', 'note': '期初'}, 'legacy').status_code == 200
    migrated = next(s for s in client.get('/api/inventory/stock-items', headers=h).get_json()['data'] if s['legacy_catalog_item_id'] == c['id'])
    path = '/api/visits/' + v['id'] + '/items'
    assert post(client, h, path, {'catalog_item_id': c['id'], 'quantity': '2', 'inventory_mode': 'manual',
        'inventory_consumption': []}, 'manual-empty').status_code == 201
    assert balance(client, h, migrated['id'])['stock_quantity'] == '10.000'
    assert post(client, h, path, {'catalog_item_id': c['id'], 'quantity': '2'}, 'old-order').status_code == 201
    assert balance(client, h, migrated['id'])['stock_quantity'] == '8.000'
    current = balance(client, h, migrated['id'])
    assert post(client, h, '/api/inventory/stock-adjust', {'stock_item_id': migrated['id'], 'version': current['version'],
        'movement_type': 'purchase', 'quantity': '1', 'input_unit': 'base', 'reason': '采购'}, 'new-writer').status_code == 200
    assert Decimal(db.session.get(CatalogItem, c['id']).stock_quantity) == Decimal('9')
    assert InventoryMovement.query.filter_by(catalog_item_id=c['id'], movement_type='purchase').count() == 1
    assert InventoryMovement.query.filter_by(catalog_item_id=c['id'], movement_type='sale').count() == 1


def test_archive_requires_writeoff_and_historical_void_restores_archive(client, admin_session):
    h = admin_session['headers']; s = stock(client, h); c, v = setup_order(client, h)
    item = post(client, h, '/api/visits/' + v['id'] + '/items', {'catalog_item_id': c['id'], 'inventory_mode': 'manual',
        'inventory_consumption': [{'stock_item_id': s['id'], 'quantity': '1'}]}, 'consume').get_json()['data']
    path = '/api/inventory/stock-items/' + s['id']; current = balance(client, h, s['id'])
    assert client.delete(path, headers={**h, 'Idempotency-Key': 'deny-delete'}, json={'version': current['version']}).status_code == 409
    assert client.delete(path, headers={**h, 'Idempotency-Key': 'delete'}, json={'version': current['version'], 'confirm_writeoff': True}).status_code == 200
    assert balance(client, h, s['id'])['stock_quantity'] == '0.000'
    assert post(client, h, '/api/visits/' + v['id'] + '/items/' + item['id'] + '/void', {}, 'void').status_code == 200
    archived = balance(client, h, s['id'])
    assert archived['stock_quantity'] == '1.000' and archived['is_active'] is False


def test_usage_ties_and_renames_keep_stable_ids(client, admin_session):
    h = admin_session['headers']; a = stock(client, h); b = stock(client, h, name='盐'); c, v = setup_order(client, h)
    row = {'catalog_item_id': c['id'], 'inventory_mode': 'manual', 'inventory_consumption': [
        {'stock_item_id': a['id'], 'quantity': '1'}, {'stock_item_id': b['id'], 'quantity': '2'}]}
    assert post(client, h, '/api/visits/' + v['id'] + '/items', row, 'usage').status_code == 201
    assert client.patch('/api/catalog/' + c['id'], headers=h, json={'name': '改名'}).status_code == 200
    rows = client.get('/api/inventory/usage', headers=h).get_json()['data']
    assert len(rows) == 2
    assert {r['catalog_name'] for r in rows} == {'改名'}
    assert all(r['usage_count'] == 1 and r['is_most_used'] for r in rows)


@pytest.mark.parametrize('extra', [
    {'inventory_mode': 'auto', 'inventory_consumption': []},
    {'inventory_mode': 'manual'}, {'inventory_consumption': []},
    {'inventory_mode': 'manual', 'inventory_consumption': [{'stock_item_id': 'a', 'quantity': '0.0001'}]},
    {'inventory_mode': 'manual', 'inventory_consumption': [{'stock_item_id': 'a', 'quantity': '1'}, {'stock_item_id': 'a', 'quantity': '1'}]},
])
def test_rejects_ambiguous_manual_selection(client, admin_session, extra):
    h = admin_session['headers']; c, v = setup_order(client, h)
    r = post(client, h, '/api/visits/' + v['id'] + '/items', {'catalog_item_id': c['id'], **extra}, 'invalid-order')
    assert r.status_code == 400


def test_stock_evidence_is_sql_immutable_and_reset_preview_tracks_balance(client, admin_session):
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError
    h = admin_session['headers']; s = stock(client, h)
    with pytest.raises(DatabaseError):
        db.session.connection().execute(text('UPDATE stock_movements SET quantity=1 WHERE stock_item_id=:id'), {'id':s['id']})
    db.session.rollback()
    from app.reset_service import period_summary
    assert period_summary()['stock_quantity'] == '950.000'


def test_stock_master_write_increments_reset_preview_revision(client, strict_owner_session):
    h = strict_owner_session['headers']
    before = client.get('/api/business/state', headers=h).get_json()['data']['business_revision']
    stock(client, h)
    after = client.get('/api/business/state', headers=h).get_json()['data']['business_revision']
    assert after > before


def test_password_authorized_force_clear_returns_service_consumption(client, admin_session):
    h = admin_session['headers']; s = stock(client,h); c,v = setup_order(client,h)
    assert post(client,h,'/api/visits/'+v['id']+'/items', {'catalog_item_id':c['id'], 'inventory_mode':'manual',
        'inventory_consumption':[{'stock_item_id':s['id'],'quantity':'1'}]}, 'force-order').status_code == 201
    path = '/api/wristbands/' + v['wristband_id'] + '/force-clear'
    assert post(client,h,path,{'password':'admin123','reason':'测试取消'},'force').status_code == 200
    assert balance(client,h,s['id'])['stock_quantity'] == '800.000'


def test_manual_product_uses_selected_stock_even_when_legacy_balance_zero(client, admin_session):
    h = admin_session['headers']; s = stock(client,h); c,v = setup_order(client,h,product=True)
    response = post(client,h,'/api/visits/'+v['id']+'/items', {'catalog_item_id':c['id'], 'quantity':'10',
        'inventory_mode':'manual','inventory_consumption':[{'stock_item_id':s['id'],'quantity':'1'}]}, 'other-stock')
    assert response.status_code == 201
    assert balance(client,h,s['id'])['stock_quantity'] == '799.000'
    assert db.session.get(CatalogItem,c['id']).stock_quantity == 0


@pytest.mark.parametrize('action', ['cancel', 'void', 'replace', 'force'])
def test_package_manual_consumption_returned_once_on_every_cancel_path(client, formal_catalog, strict_owner_session, action):
    from app.models import Wristband, Visit
    h = strict_owner_session['headers']; s = stock(client,h)
    band = Wristband.query.filter_by(number='001').one()
    v = post(client,h,'/api/wristbands/'+band.id+'/open',{},'open').get_json()['data']
    package = CatalogItem.query.filter_by(reference_code='package.A').one()
    path = '/api/visits/'+v['id']+'/items/batch'
    body = {'items':[{'catalog_item_id':package.id,'quantity':'1','inventory_mode':'manual',
        'inventory_consumption':[{'stock_item_id':s['id'],'quantity':'1'}]}]}
    response = post(client,h,path,body,'package-stock')
    assert response.status_code == 201
    parent = response.get_json()['data'][0]
    assert balance(client,h,s['id'])['stock_quantity'] == '799.000'
    same = post(client,h,path,body,'package-repeat')
    assert same.status_code == 201
    assert same.get_json()['data'][0]['id'] == parent['id']
    assert balance(client,h,s['id'])['stock_quantity'] == '799.000'
    different = {'items':[{**body['items'][0], 'inventory_consumption':[]}]}
    assert post(client,h,path,different,'package-different').status_code == 409
    if action == 'force':
        r = post(client,h,'/api/wristbands/'+band.id+'/force-clear',{'password':strict_owner_session['password'], 'reason':'取消测试'},'force-package')
    elif action == 'void':
        r = post(client,h,'/api/visits/'+v['id']+'/items/'+parent['id']+'/void',{},'void-package')
    elif action == 'cancel':
        r = client.delete('/api/visits/'+v['id']+'/package',headers={**h,'Idempotency-Key':'cancel-package'},
            json={'version':db.session.get(Visit,v['id']).version})
    else:
        r = post(client,h,'/api/visits/'+v['id']+'/package',{'catalog_item_id':CatalogItem.query.filter_by(reference_code='package.B').one().id,
            'version':db.session.get(Visit,v['id']).version,'confirm_replace':True},'replace-package')
    assert r.status_code == 200
    assert balance(client,h,s['id'])['stock_quantity'] == '800.000'
    if action == 'force':
        assert all(row.covered_quantity == 0 and row.package_order_item_id is None
                   for row in OrderItem.query.filter_by(visit_id=v['id']).all())


def test_settled_order_cannot_acquire_new_consumption_evidence(client, admin_session):
    from app.models import OrderStockConsumption
    from sqlalchemy.exc import DatabaseError
    h = admin_session['headers']; s = stock(client,h); c,v = setup_order(client,h)
    item = post(client,h,'/api/visits/'+v['id']+'/items',{'catalog_item_id':c['id'],
        'inventory_mode':'manual','inventory_consumption':[]},'empty').get_json()['data']
    assert post(client,h,'/api/checkout', {'visit_ids':[v['id']], 'payments':[{'method':'cash','amount':'20'}]},'settle').status_code == 201
    db.session.add(OrderStockConsumption(order_item_id=item['id'],stock_item_id=s['id'],
        stock_name_snapshot='伪造',base_unit_snapshot='袋',quantity=1))
    with pytest.raises(DatabaseError): db.session.flush()
    db.session.rollback()


def test_package_manual_empty_selection_remains_explicit(client, formal_catalog, strict_owner_session):
    from app.models import Wristband
    h = strict_owner_session['headers']
    band = Wristband.query.filter_by(number='001').one()
    v = post(client,h,'/api/wristbands/'+band.id+'/open',{},'open-empty-package').get_json()['data']
    p = CatalogItem.query.filter_by(reference_code='package.A').one()
    r = post(client,h,'/api/visits/'+v['id']+'/items/batch',{'items':[{'catalog_item_id':p.id,
        'inventory_mode':'manual','inventory_consumption':[]}]},'package-empty')
    assert r.status_code == 201
    assert r.get_json()['data'][0]['inventory_mode'] == 'manual'
    assert r.get_json()['data'][0]['inventory_consumption'] == []


def test_reactivated_legacy_product_can_sell_without_reopening_explicit_archive(client, admin_session):
    from app.models import StockItem
    from app.stock_service import legacy_stock
    h = admin_session['headers']
    catalog = CatalogItem(name='停用旧商品',kind='product',price=20,stock_tracked=True,
        stock_quantity=5,is_active=False)
    db.session.add(catalog); db.session.flush()
    master = legacy_stock(catalog); db.session.commit()
    stock_id, catalog_id = master.id,catalog.id
    assert master.is_active is False
    assert client.patch('/api/catalog/'+catalog_id,headers=h,json={'is_active':True}).status_code == 200
    _,v = setup_order(client,h)
    path = '/api/visits/'+v['id']+'/items'
    first = post(client,h,path,{'catalog_item_id':catalog_id,'quantity':'1'},'reactivation-sale')
    assert first.status_code == 201,first.get_json()
    current = balance(client,h,stock_id)
    assert current['is_active'] is True and current['stock_quantity'] == '4.000'
    archived = client.delete('/api/inventory/stock-items/'+stock_id,headers={**h,'Idempotency-Key':'explicit-archive'},
        json={'version':current['version'],'confirm_writeoff':True})
    assert archived.status_code == 200
    assert client.patch('/api/catalog/'+catalog_id,headers=h,json={'is_active':False}).status_code == 200
    assert client.patch('/api/catalog/'+catalog_id,headers=h,json={'is_active':True,'name':'再次启用'}).status_code == 200
    assert balance(client,h,stock_id)['is_active'] is False
    assert balance(client,h,stock_id)['stock_quantity'] == '0.000'
    denied = post(client,h,path,{'catalog_item_id':catalog_id,'quantity':'1'},'archived-sale')
    assert denied.status_code == 404 and denied.get_json()['error']['code'] == 'STOCK_NOT_AVAILABLE'
    assert db.session.get(StockItem,stock_id).is_active is False


def test_zero_balance_mapped_archive_cannot_be_reactivated_by_catalog(client, admin_session):
    from app.models import StockMovement
    from app.stock_service import legacy_stock
    h = admin_session['headers']
    catalog = CatalogItem(name='零库存旧商品',kind='product',price=20,stock_tracked=True,
        stock_quantity=0,is_active=True)
    db.session.add(catalog); db.session.flush()
    master = legacy_stock(catalog); db.session.commit()
    stock_id,catalog_id,version = master.id,catalog.id,master.version
    archived = client.delete('/api/inventory/stock-items/'+stock_id,
        headers={**h,'Idempotency-Key':'zero-archive'},json={'version':version})
    assert archived.status_code == 200
    assert StockMovement.query.count() == 0
    assert client.patch('/api/catalog/'+catalog_id,headers=h,json={'is_active':False}).status_code == 200
    assert client.patch('/api/catalog/'+catalog_id,headers=h,json={'is_active':True}).status_code == 200
    assert balance(client,h,stock_id)['is_active'] is False


@pytest.mark.parametrize('route', ['desktop','mobile'])
def test_package_replacement_can_reuse_last_recorded_stock_atomically(client,formal_catalog,strict_owner_session,route):
    from app.models import Wristband,StockMovement,OrderStockConsumption
    h = strict_owner_session['headers']; s = stock(client,h,opening_quantity='1',opening_unit='base')
    other = stock(client,h,name='另一个耗材',opening_quantity='1',opening_unit='base')
    band = Wristband.query.filter_by(number='001').one()
    v = post(client,h,'/api/wristbands/'+band.id+'/open',{},'replacement-open').get_json()['data']
    path = ('/api/visits/' if route=='desktop' else '/api/mobile/visits/')+v['id']+'/items'
    if route=='desktop': path += '/batch'
    a = CatalogItem.query.filter_by(reference_code='package.A').one()
    b = CatalogItem.query.filter_by(reference_code='package.B').one()
    def body(catalog_id,quantity='1',extra=None):
        selections = [{'stock_item_id':s['id'],'quantity':quantity}]
        if extra: selections.append({'stock_item_id':other['id'],'quantity':extra})
        return {'confirm_replace':True,'items':[{'catalog_item_id':catalog_id,'inventory_mode':'manual',
            'inventory_consumption':selections}]}
    first = post(client,h,path,body(a.id),'package-last-a')
    assert first.status_code == 201
    parent_id = first.get_json()['data'][0]['id']
    assert balance(client,h,s['id'])['stock_quantity'] == '0.000'
    count = StockMovement.query.count()
    repeated = post(client,h,path,body(a.id),'same-package-zero-stock')
    assert repeated.status_code == 201
    assert repeated.get_json()['data'][0]['id'] == parent_id
    assert StockMovement.query.count() == count
    # Net replacement shortage must not cancel the original or return its stock.
    insufficient = post(client,h,path,body(b.id,quantity='2'),'replace-too-much')
    assert insufficient.status_code == 409
    assert db.session.get(OrderItem,parent_id).status == 'active'
    assert balance(client,h,s['id'])['stock_quantity'] == '0.000'
    assert StockMovement.query.count() == count
    assert OrderStockConsumption.query.count() == 1
    # The old unit is credited once across all new lines, not once per line.
    aggregate_body = body(b.id)
    ordinary = CatalogItem.query.filter_by(reference_code='bath.scrub').one()
    aggregate_body['items'].append({'catalog_item_id':ordinary.id,'inventory_mode':'manual',
        'inventory_consumption':[{'stock_item_id':s['id'],'quantity':'1'}]})
    aggregate_shortage = post(client,h,path,aggregate_body,'replace-aggregate-shortage')
    assert aggregate_shortage.status_code == 409
    assert db.session.get(OrderItem,parent_id).status == 'active'
    assert balance(client,h,s['id'])['stock_quantity'] == '0.000'
    assert StockMovement.query.count() == count
    # All affected masters participate: a second insufficient selected item also rolls back.
    insufficient_other = post(client,h,path,body(b.id,extra='2'),'replace-other-shortage')
    assert insufficient_other.status_code == 409
    assert db.session.get(OrderItem,parent_id).status == 'active'
    assert balance(client,h,other['id'])['stock_quantity'] == '1.000'
    assert StockMovement.query.count() == count
    replacement_body = body(b.id,extra='1')
    replaced = post(client,h,path,replacement_body,'package-last-b')
    assert replaced.status_code == 201,replaced.get_json()
    new_parent = replaced.get_json()['data'][0]['id']
    assert new_parent != parent_id
    assert db.session.get(OrderItem,parent_id).status == 'voided'
    assert balance(client,h,s['id'])['stock_quantity'] == '0.000'
    assert balance(client,h,other['id'])['stock_quantity'] == '0.000'
    assert StockMovement.query.filter_by(stock_item_id=s['id'],movement_type='void_return').count() == 1
    assert StockMovement.query.filter_by(stock_item_id=s['id'],movement_type='sale').count() == 2
    replay = post(client,h,path,replacement_body,'package-last-b')
    assert replay.status_code in {200,201}
    assert StockMovement.query.filter_by(stock_item_id=s['id'],movement_type='void_return').count() == 1
    assert StockMovement.query.filter_by(stock_item_id=s['id'],movement_type='sale').count() == 2
