from decimal import Decimal as D

import pytest

from app.audit_service import verify_audit_chain
from app.extensions import db
from app.models import CatalogItem, InventoryMovement, OrderItem, Visit, Wristband


def open_visit(client, headers, number='001'):
    band=Wristband.query.filter_by(number=number,is_active=True).one()
    response=client.post(f'/api/wristbands/{band.id}/open',headers=headers,json={})
    assert response.status_code==201
    return response.get_json()['data']['id']


def item(code): return CatalogItem.query.filter_by(reference_code=code).one()
def total(visit_id):
    return sum((line.total_amount for line in OrderItem.query.filter_by(visit_id=visit_id,status='active')),D(0))


def add(client,headers,visit_id,rows,key='add'):
    response=client.post(f'/api/visits/{visit_id}/items/batch',headers=headers,json={
        'version':db.session.get(Visit,visit_id).version,'idempotency_key':key,
        'items':[{'catalog_item_id':item(code).id,'quantity':qty} for code,qty in rows]})
    assert response.status_code==201,response.get_json()
    return response.get_json()['data']


def package(client,headers,visit_id,code='A',key='package',**extra):
    return client.post(f'/api/visits/{visit_id}/package',headers=headers,json={
        'catalog_item_id':item('package.'+code).id,'version':db.session.get(Visit,visit_id).version,
        'idempotency_key':key,**extra})


def test_package_a_real_orders_have_one_charge_plus_water_and_extra_cup(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    add(client,h,visit_id,[('bath.scrub',1),('bath.cup',1)])
    assert total(visit_id)==40
    response=package(client,h,visit_id)
    assert response.status_code==200,response.get_json()
    assert total(visit_id)==45
    # Inclusion descriptions do not manufacture supplies/stock sales.
    assert OrderItem.query.filter_by(visit_id=visit_id,status='active').count()==4
    assert InventoryMovement.query.count()==0
    water=CatalogItem(kind='product',name='测试水',price=D(3),reference_code='test.water',stock_tracked=False)
    db.session.add(water); db.session.commit()
    add(client,h,visit_id,[('test.water',1)],key='water')
    assert total(visit_id)==48
    add(client,h,visit_id,[('bath.cup',1)],key='extra-cup')
    assert total(visit_id)==63
    cups=OrderItem.query.filter_by(visit_id=visit_id,catalog_item_id=item('bath.cup').id,status='active').all()
    assert sum(line.covered_quantity for line in cups)==1
    assert verify_audit_chain()==(True,None)


def test_package_change_cancel_and_void_do_not_double_move_stock(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    supplies=item('bath.supplies')
    # Preserve legacy tracked-product/package coverage independently of the
    # approved new bath service defaults. Historical tracked goods still work.
    supplies.kind='product'; supplies.stock_tracked=True
    db.session.commit()
    client.post('/api/inventory/adjust',headers=h,json={'catalog_item_id':supplies.id,
        'quantity':10,'movement_type':'purchase','note':'隔离采购','idempotency_key':'stock'})
    sale=add(client,h,visit_id,[('bath.supplies',3)])[0]
    assert supplies.stock_quantity==7
    assert package(client,h,visit_id).status_code==200
    line=db.session.get(OrderItem,sale['id'])
    assert (line.quantity,line.covered_quantity,line.total_amount)==(D(3),D(1),D(14))
    assert total(visit_id)==59
    assert package(client,h,visit_id,'B','needs-confirm').status_code==409
    assert total(visit_id)==59
    assert package(client,h,visit_id,'B','replace',confirm_replace=True).status_code==200
    assert total(visit_id)==69
    assert supplies.stock_quantity==7
    movement_count=InventoryMovement.query.count()
    response=client.delete(f'/api/visits/{visit_id}/package',headers=h,json={
        'version':db.session.get(Visit,visit_id).version,'idempotency_key':'cancel'})
    assert response.status_code==200,response.get_json()
    assert total(visit_id)==36
    assert InventoryMovement.query.count()==movement_count
    assert OrderItem.query.filter_by(visit_id=visit_id,kind='package',status='active').count()==0
    void=client.post(f'/api/visits/{visit_id}/items/{line.id}/void',headers=h,json={'idempotency_key':'void'})
    assert void.status_code==200
    assert supplies.stock_quantity==10
    assert client.post(f'/api/visits/{visit_id}/items/{line.id}/void',headers=h,json={'idempotency_key':'void'}).status_code==200
    assert supplies.stock_quantity==10
    assert verify_audit_chain()==(True,None)


@pytest.mark.parametrize('extra,status',[({'total_amount':'0.01'},400),({'covered_quantity':1},400),({'unit_price':0},400),
    ({'confirm_replace':'true'},400),({'catalog_item_id':'missing'},404),({'version':-1},409),
    ({'catalog_item_id':[]},400)])
def test_bad_package_input_leaves_no_parent_or_ticket_coverage(client,formal_catalog,strict_owner_session,extra,status):
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    response=package(client,h,visit_id,**extra)
    assert response.status_code==status
    if status==404: assert response.get_json()['error']['code']=='ITEM_NOT_AVAILABLE'
    assert total(visit_id)==15
    assert OrderItem.query.filter_by(visit_id=visit_id,kind='package').count()==0
    assert all(line.covered_quantity==0 for line in OrderItem.query.filter_by(visit_id=visit_id))


def test_package_replay_is_hash_bound_and_does_not_duplicate_parent(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    body={'catalog_item_id':item('package.A').id,'version':db.session.get(Visit,visit_id).version,'idempotency_key':'same'}
    first=client.post(f'/api/visits/{visit_id}/package',headers=h,json=body)
    assert first.status_code==200
    again=client.post(f'/api/visits/{visit_id}/package',headers=h,json=body)
    assert again.status_code==200
    assert again.get_json()['data']==first.get_json()['data']
    assert OrderItem.query.filter_by(visit_id=visit_id,kind='package').count()==1
    bad=client.post(f'/api/visits/{visit_id}/package',headers=h,json={**body,'catalog_item_id':item('package.B').id})
    assert bad.status_code==409
    assert total(visit_id)==45


def test_batch_package_and_actual_services_commit_once_or_roll_back_together(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    # This rollback case needs a physical product, not the new no-stock service.
    supplies=item('bath.supplies')
    supplies.kind='product'; supplies.stock_tracked=True
    db.session.commit()
    response=client.post(f'/api/visits/{visit_id}/items/batch',headers=h,json={'idempotency_key':'out-stock',
        'items':[{'catalog_item_id':item('package.A').id,'quantity':1},
            {'catalog_item_id':item('bath.supplies').id,'quantity':1}]})
    assert response.status_code==409
    assert OrderItem.query.filter_by(visit_id=visit_id).count()==1
    assert total(visit_id)==15
    add(client,h,visit_id,[('package.A',1),('bath.scrub',1),('bath.cup',1)],'mixed-package')
    assert total(visit_id)==45
    assert InventoryMovement.query.count()==0
    rejected=client.post(f'/api/visits/{visit_id}/items/batch',headers=h,json={'idempotency_key':'two-packages',
        'items':[{'catalog_item_id':item('package.A').id,'quantity':1},
            {'catalog_item_id':item('package.B').id,'quantity':1}]})
    assert rejected.status_code==400
    assert OrderItem.query.filter_by(visit_id=visit_id,kind='package',status='active').count()==1


def test_change_ticket_and_open_prices_recompute_net_without_reducing_package_twice(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    add(client,h,visit_id,[('bath.scrub',1)])
    assert package(client,h,visit_id).status_code==200
    response=client.patch(f'/api/visits/{visit_id}/ticket',headers=h,json={'ticket_catalog_item_id':item('ticket.child').id,
        'version':db.session.get(Visit,visit_id).version,'idempotency_key':'change-ticket'})
    assert response.status_code==200
    assert total(visit_id)==45
    response=client.patch(f'/api/catalog/{item("bath.scrub").id}',headers=h,json={'price':'20.00'})
    assert response.status_code==200
    scrub=OrderItem.query.filter_by(visit_id=visit_id,catalog_item_id=item('bath.scrub').id,status='active').one()
    assert scrub.unit_price==20 and scrub.total_amount==0
    assert total(visit_id)==45
    assert client.patch(f'/api/catalog/{item("package.A").id}',headers=h,json={'price':'50.00'}).status_code==200
    assert total(visit_id)==50


def test_mobile_bound_admin_sees_and_selects_package_but_staff_cannot(client,formal_catalog,strict_owner_session):
    from app.auth_service import hash_password
    from app.models import Employee
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    def login(username,password):
        response=client.post('/api/auth/login',json={'username':username,'password':password,
            'terminal_code':strict_owner_session['terminal_code'],'client_channel':'mobile'})
        assert response.status_code==200
        return {'Authorization':'Bearer '+response.get_json()['data']['access_token'],
            'X-Business-Period':h['X-Business-Period']}
    mh=login('fixture-owner',strict_owner_session['password'])
    bootstrap=client.get('/api/mobile/bootstrap',headers=mh).get_json()['data']
    assert item('package.A').id in {row['id'] for row in bootstrap['catalog']}
    assert client.post(f'/api/mobile/visits/{visit_id}/package',headers=mh,json={
        'catalog_item_id':item('package.A').id,'version':db.session.get(Visit,visit_id).version,'idempotency_key':'mobile-A'}).status_code==200
    db.session.add(Employee(username='fixture-scrub',display_name='隔离男浴',role='male_scrubber',
        password_hash=hash_password('fixture-password'),allowed_channels=['mobile']))
    db.session.commit()
    sh=login('fixture-scrub','fixture-password')
    bootstrap=client.get('/api/mobile/bootstrap',headers=sh).get_json()['data']
    assert not any(row['kind']=='package' for row in bootstrap['catalog'])
    before=total(visit_id)
    forbidden=client.post(f'/api/mobile/visits/{visit_id}/package',headers=sh,json={
        'catalog_item_id':item('package.B').id,'version':db.session.get(Visit,visit_id).version,'idempotency_key':'staff-package'})
    assert forbidden.status_code==403
    assert total(visit_id)==before
    added=client.post(f'/api/mobile/visits/{visit_id}/items',headers={**sh,'Idempotency-Key':'staff-scrub'},
        json={'items':[{'catalog_item_id':item('bath.scrub').id,'quantity':1}]})
    assert added.status_code==201
    assert added.get_json()['data'][0]['total_amount']=='0.00'


def test_package_definition_edit_reprices_open_snapshot_not_stock(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    add(client,h,visit_id,[('bath.scrub',1),('bath.cup',1)])
    assert package(client,h,visit_id).status_code==200
    definition=dict(item('package.A').package_definition)
    definition['slots']=[slot for slot in definition['slots'] if item('bath.cup').id not in slot['catalog_item_ids']]
    response=client.patch(f'/api/catalog/{item("package.A").id}',headers=h,json={'package_definition':definition})
    assert response.status_code==200
    assert total(visit_id)==60
    assert InventoryMovement.query.count()==0
    parent=OrderItem.query.filter_by(visit_id=visit_id,kind='package',status='active').one()
    assert parent.package_snapshot['slots']==definition['slots']


@pytest.mark.parametrize('mutation',['missing','overlap','zero','package-ref','no-ticket','precision','oversized'])
def test_bad_definition_does_not_change_catalog_or_open_snapshot(client,formal_catalog,strict_owner_session,mutation):
    from copy import deepcopy
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    assert package(client,h,visit_id).status_code==200
    catalog=item('package.A'); before=deepcopy(catalog.package_definition)
    bad=deepcopy(before)
    if mutation=='missing': bad['slots'][1]['catalog_item_ids']=['missing']
    elif mutation=='overlap': bad['slots'].append(deepcopy(bad['slots'][1]))
    elif mutation=='zero': bad['slots'][1]['quantity']='0'
    elif mutation=='package-ref': bad['slots'][1]['catalog_item_ids']=[item('package.B').id]
    elif mutation=='precision': bad['slots'][1]['quantity']='0.0001'
    elif mutation=='oversized': bad['slots'][1]['quantity']='1e1000'
    else: bad['slots']=bad['slots'][1:]
    response=client.patch(f'/api/catalog/{catalog.id}',headers=h,json={'package_definition':bad})
    assert response.status_code==400
    assert catalog.package_definition==before
    assert total(visit_id)==45


@pytest.mark.parametrize('extra',[{'total_amount':'0.01'},{'unit_price':'0.01'},{'covered_quantity':1}])
def test_batch_rejects_client_billing_fields(client,formal_catalog,strict_owner_session,extra):
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    response=client.post(f'/api/visits/{visit_id}/items/batch',headers=h,json={'idempotency_key':'fake-net',
        'items':[{'catalog_item_id':item('package.A').id,'quantity':1,**extra}]})
    assert response.status_code==400
    assert OrderItem.query.filter_by(visit_id=visit_id,kind='package').count()==0


def test_new_package_write_grant_exists_for_cashier_but_not_staff(client,formal_catalog,strict_owner_session):
    from app.auth_service import hash_password
    from app.models import Employee
    h=strict_owner_session['headers']; visit_id=open_visit(client,h)
    db.session.add(Employee(username='fixture-cashier',display_name='隔离收银',role='cashier',
        password_hash=hash_password('fixture-password'),allowed_channels=['desktop']))
    db.session.commit()
    login=client.post('/api/auth/login',json={'username':'fixture-cashier','password':'fixture-password',
        'terminal_code':strict_owner_session['terminal_code'],'client_channel':'desktop'})
    assert login.status_code==200
    cashier={'Authorization':'Bearer '+login.get_json()['data']['access_token'],'X-Business-Period':h['X-Business-Period']}
    assert package(client,cashier,visit_id).status_code==200
    assert total(visit_id)==45
