from decimal import Decimal

import pytest

from app.audit_service import verify_audit_chain
from app.extensions import db
from app.models import AuditLog, CatalogItem, OrderItem, Visit, Wristband


def band(number): return Wristband.query.filter_by(number=number,is_active=True).one()
def ticket(code): return CatalogItem.query.filter_by(reference_code='ticket.'+code).one()
def active_ticket(visit_id): return OrderItem.query.filter_by(visit_id=visit_id,kind='ticket',status='active').one()


@pytest.mark.parametrize('number,code,amount', [('001',None,'15.00'),('051','child','10.00')])
def test_admission_price_comes_from_selected_server_ticket(client,formal_catalog,strict_owner_session,number,code,amount):
    body = {'ticket_catalog_item_id':ticket(code).id} if code else {}
    response = client.post(f'/api/wristbands/{band(number).id}/open',headers=strict_owner_session['headers'],json=body)
    assert response.status_code==201
    assert response.get_json()['data']['total_amount']==amount
    line = active_ticket(response.get_json()['data']['id'])
    assert line.unit_price==Decimal(amount)


def test_link_batch_selects_each_new_ticket_but_preserves_existing_child(client,formal_catalog,strict_owner_session):
    headers = strict_owner_session['headers']
    first = client.post(f'/api/wristbands/{band("001").id}/open',headers=headers,
        json={'ticket_catalog_item_id':ticket('child').id}).get_json()['data']['id']
    second, third = band('002'),band('051')
    response = client.post('/api/wristbands/link-batch',headers=headers,json={
        'wristband_ids':[band('001').id,second.id,third.id],
        'ticket_catalog_item_ids':{band('001').id:ticket('adult').id,second.id:ticket('adult').id,third.id:ticket('child').id}})
    assert response.status_code==200
    assert active_ticket(first).unit_price==10
    for row,price in [(second,15),(third,10)]:
        visit = Visit.query.filter_by(wristband_id=row.id,status='open').one()
        assert active_ticket(visit.id).unit_price==price


@pytest.mark.parametrize('bad', ['service','product','inactive','forged-money'])
def test_invalid_ticket_or_client_price_does_not_open_visit(client,formal_catalog,strict_owner_session,bad):
    if bad=='forged-money': body={'ticket_catalog_item_id':ticket('child').id,'price':'0.01'}
    elif bad=='inactive':
        row=ticket('child'); row.is_active=False; db.session.commit()
        body={'ticket_catalog_item_id':row.id}
    else: body={'ticket_catalog_item_id':CatalogItem.query.filter_by(kind=bad,is_active=True).first().id}
    response=client.post(f'/api/wristbands/{band("001").id}/open',headers=strict_owner_session['headers'],json=body)
    assert response.status_code==400
    assert Visit.query.count()==0
    assert band('001').status=='available'


def test_ticket_change_keeps_old_line_and_replays_without_duplicate(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']
    visit_id=client.post(f'/api/wristbands/{band("001").id}/open',headers=h,json={}).get_json()['data']['id']
    old_id=active_ticket(visit_id).id
    visit=db.session.get(Visit,visit_id)
    body={'ticket_catalog_item_id':ticket('child').id,'version':visit.version,'idempotency_key':'child-change'}
    response=client.patch(f'/api/visits/{visit_id}/ticket',headers=h,json=body)
    assert response.status_code==200
    assert response.get_json()['data']['total_amount']=='10.00'
    assert db.session.get(OrderItem,old_id).status=='voided'
    assert active_ticket(visit_id).unit_price==10
    assert client.patch(f'/api/visits/{visit_id}/ticket',headers=h,json=body).status_code==200
    assert OrderItem.query.filter_by(visit_id=visit_id,kind='ticket').count()==2
    assert AuditLog.query.filter_by(action='visit.ticket_change').count()==1
    assert verify_audit_chain()==(True,None)
    changed={**body,'ticket_catalog_item_id':ticket('adult').id}
    assert client.patch(f'/api/visits/{visit_id}/ticket',headers=h,json=changed).status_code==409


def test_stale_ticket_change_and_settled_ticket_are_rejected(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']
    visit_id=client.post(f'/api/wristbands/{band("001").id}/open',headers=h,json={}).get_json()['data']['id']
    body={'ticket_catalog_item_id':ticket('child').id,'version':-1,'idempotency_key':'stale-ticket'}
    assert client.patch(f'/api/visits/{visit_id}/ticket',headers=h,json=body).status_code==409
    visit=db.session.get(Visit,visit_id)
    result=client.post('/api/checkout',headers=h,json={'visit_ids':[visit_id],
        'payments':[{'method':'cash','amount':'15.00'}],'idempotency_key':'settle-ticket'})
    assert result.status_code==201
    body={**body,'version':visit.version,'idempotency_key':'closed-ticket'}
    assert client.patch(f'/api/visits/{visit_id}/ticket',headers=h,json=body).status_code==409
    assert active_ticket(visit_id).total_amount==15


@pytest.mark.parametrize('role',['male_scrubber','female_scrubber','floor_attendant'])
def test_ordinary_staff_cannot_change_admission(client,formal_catalog,strict_owner_session,role):
    h=strict_owner_session['headers']
    visit_id=client.post(f'/api/wristbands/{band("001").id}/open',headers=h,json={}).get_json()['data']['id']
    response=client.post('/api/employees',headers=h,json={'username':role,'display_name':role,
        'password':'fixture-only-12345','role':role,'is_active':True,'allowed_channels':['desktop']})
    assert response.status_code==201
    login=client.post('/api/auth/login',json={'username':role,'password':'fixture-only-12345',
        'terminal_code':strict_owner_session['terminal_code'],'client_channel':'desktop'})
    assert login.status_code==200
    staff={'Authorization':'Bearer '+login.get_json()['data']['access_token'],
        'X-Business-Period':login.get_json()['data']['business_state']['period_id']}
    assert client.patch(f'/api/visits/{visit_id}/ticket',headers=staff,json={
        'ticket_catalog_item_id':ticket('child').id,'version':db.session.get(Visit,visit_id).version,
        'idempotency_key':'staff-ticket'}).status_code==403
    assert active_ticket(visit_id).total_amount==15


def test_retired_bands_cannot_reenter_current_open_switch_or_recovery(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']
    retired=Wristband.query.filter_by(number='8001').one()
    assert not retired.is_active
    assert client.post(f'/api/wristbands/{retired.id}/open',headers=h,json={}).status_code==409
    current=band('001')
    assert client.post(f'/api/wristbands/{current.id}/open',headers=h,json={}).status_code==201
    assert client.post(f'/api/wristbands/{current.id}/switch',headers=h,json={'target_number':'8001'}).status_code==409
    retired.status='lost'; db.session.commit()
    assert client.post(f'/api/wristbands/{retired.id}/recover',headers=h,json={}).status_code==409
    rows=client.get('/api/wristbands',headers=h).get_json()['data']
    assert len(rows)==100 and all(len(row['number'])==3 for row in rows)


def test_current_number_lookup_normalizes_one_without_changing_history(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']
    first=band('001')
    client.post(f'/api/wristbands/{first.id}/open',headers=h,json={})
    response=client.post(f'/api/wristbands/{first.id}/switch',headers=h,json={'target_number':'51'})
    assert response.status_code==200
    assert response.get_json()['data']['wristband']['number']=='051'
    assert Wristband.query.filter_by(number='9001').one().number=='9001'
