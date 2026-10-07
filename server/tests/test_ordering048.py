"""Cost edits authenticate the current account and never change receipt/stock history."""
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import AuditLog, CatalogItem, StockItem, StockMovement
from test_inventory047 import create, post


def patch(client, headers, item, body, key):
    return client.patch('/api/inventory/stock-items/' + item['id'],
        headers={**headers, 'Idempotency-Key': key}, json={'version':item['version'], **body})


def test_first_master_cost_zero_needs_no_password_and_replays_exactly(client, admin_session):
    h=admin_session['headers']; item=create(client,h)
    assert item.get('unit_cost', 'missing') is None
    r=patch(client,h,item,{'unit_cost':'0'},'master-first')
    assert r.status_code==200, r.get_json()
    result=r.get_json()['data']
    assert result['unit_cost']=='0.00' and result['stock_quantity']=='800.000'
    assert patch(client,h,item,{'unit_cost':'0'},'master-first').get_json()['data']==result
    assert StockMovement.query.filter_by(stock_item_id=item['id']).count()==1


def test_initialized_master_cost_rejects_missing_wrong_password_without_editing_other_fields(client,admin_session):
    h=admin_session['headers']; item=create(client,h)
    r=patch(client,h,item,{'unit_cost':'0'},'set-zero')
    assert r.status_code==200, r.get_json()
    assigned=r.get_json()['data']
    for key,password in [('no-password',None),('bad-password','not-current-password')]:
        body={'unit_cost':'0.60','name':'must-not-be-committed'}
        if password: body['password']=password
        denied=patch(client,h,assigned,body,key)
        assert denied.status_code==403,denied.get_json()
        db.session.expire_all()
        actual=db.session.get(StockItem,item['id'])
        assert actual.unit_cost==Decimal('0') and actual.name==item['name']
        assert actual.version==assigned['version']
    changed=patch(client,h,assigned,{'unit_cost':'0.60','password':'admin123'},'correct-password')
    assert changed.status_code==200,changed.get_json()
    assert changed.get_json()['data']['unit_cost']=='0.60'
    events=AuditLog.query.filter_by(action='stock.update',entity_id=item['id']).order_by(AuditLog.chain_index).all()
    assert events[-1].details['before']['unit_cost']=='0.00'
    assert events[-1].details['after']['unit_cost']=='0.60'
    assert 'admin123' not in str(events[-1].details)


def test_same_cost_and_unrelated_edit_do_not_reauthenticate_but_stale_first_assignment_is_rejected(client,admin_session):
    h=admin_session['headers']; item=create(client,h)
    r=patch(client,h,item,{'unit_cost':'1.20'},'first-value')
    assert r.status_code==200,r.get_json()
    assigned=r.get_json()['data']
    assert patch(client,h,item,{'unit_cost':'9'},'stale-first').status_code==409
    same=patch(client,h,assigned,{'unit_cost':'1.2','name':'改名保留成本'},'same-value')
    assert same.status_code==200,same.get_json()
    assert same.get_json()['data']['name']=='改名保留成本'


@pytest.mark.parametrize('role',['cashier','inventory'])
def test_operator_cannot_use_another_administrators_password(client,strict_owner_session,role):
    owner=strict_owner_session
    r=client.post('/api/employees',headers=owner['headers'],json={'username':'cost-'+role,
        'display_name':role,'role':role,'password':'operator-cost-2026','allowed_channels':['desktop']})
    assert r.status_code==201,r.get_json()
    login=client.post('/api/auth/login',json={'username':'cost-'+role,'password':'operator-cost-2026',
        'terminal_code':'ENTRY-TEST','client_channel':'desktop'}).get_json()['data']
    h={'Authorization':'Bearer '+login['access_token'],'X-Business-Period':login['business_state']['period_id']}
    item=create(client,h)
    first=patch(client,h,item,{'unit_cost':'1'},'operator-first')
    assert first.status_code==200,first.get_json()
    assigned=first.get_json()['data']
    denied=patch(client,h,assigned,{'unit_cost':'2','password':owner['password']},'other-user-password')
    assert denied.status_code==403,denied.get_json()
    accepted=patch(client,h,assigned,{'unit_cost':'2','password':'operator-cost-2026'},'own-user-password')
    assert accepted.status_code==200,accepted.get_json()


@pytest.mark.parametrize('raw',[None,True,'-1','0.001','NaN','Infinity','10000000000'])
def test_master_cost_rejects_invalid_or_clear_values(client,admin_session,raw):
    h=admin_session['headers']; item=create(client,h)
    r=patch(client,h,item,{'unit_cost':raw},'invalid-master')
    assert r.status_code==400 and r.get_json()['error']['code']=='INVALID_STOCK_COST'


def test_changing_receipt_cost_also_requires_own_password_and_keeps_quantity(client,admin_session):
    h=admin_session['headers']; item=create(client,h,unit_cost='120')
    movement=client.get('/api/inventory/stock-movements',headers=h).get_json()['data'][0]
    path='/api/inventory/stock-movements/'+movement['id']+'/cost'
    body={'expected_cost_id':movement['cost']['id'],'unit_cost':'100'}
    assert post(client,h,path,body,'receipt-no-password').status_code==403
    r=post(client,h,path,{**body,'password':'admin123'},'receipt-correct')
    assert r.status_code==200,r.get_json()
    assert r.get_json()['data']['cost']['total_cost']=='400.00'
    assert db.session.get(StockItem,item['id']).stock_quantity==Decimal('800')


def test_formal_three_items_are_services_without_changing_their_prices():
    from app.catalog_defaults import formal_catalog_specs
    rows={row.name:row for row in formal_catalog_specs()}
    for name,price in [('澡巾','6'),('备品','7'),('搓泥宝','10')]:
        assert rows[name].kind=='service' and rows[name].stock_tracked is False
        assert rows[name].price==Decimal(price)


def test_additive_migration_preserves_quantity_and_receipts_and_only_reclassifies_three_products(client,admin_session):
    from app import schema_maintenance
    upgrade = schema_maintenance.upgrade_ordering048_schema
    h=admin_session['headers']; item=create(client,h,unit_cost='120')
    products=[CatalogItem(name=name,kind='product',price=price,stock_tracked=True,stock_quantity=30)
              for name,price in [('澡巾',6),('备品',7),('搓泥宝',10),('饮料',5)]]
    db.session.add_all(products);db.session.commit()
    ids=[row.id for row in products]
    with db.engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE stock_items DROP COLUMN unit_cost')
        upgrade(connection)
        upgrade(connection)
    db.session.expire_all()
    master=db.session.get(StockItem,item['id'])
    assert master.stock_quantity==Decimal('800') and master.unit_cost is None
    assert StockMovement.query.filter_by(stock_item_id=item['id']).count()==1
    for index,id_ in enumerate(ids):
        row=db.session.get(CatalogItem,id_)
        assert row.kind==('service' if index<3 else 'product')
        assert row.stock_tracked==(index==3) and row.stock_quantity==Decimal('30')
    movement=client.get('/api/inventory/stock-movements',headers=h).get_json()['data'][0]
    assert movement['cost']['total_cost']=='480.00'
