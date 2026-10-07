from decimal import Decimal as D

import pytest

from app.audit_service import verify_audit_chain
from app.extensions import db
from app.financial_integrity import check_financial_integrity
from app.models import CatalogItem, Member, OrderItem, Payment, Settlement, Visit, Wristband
from test_package_orders import add, item, open_visit, package, total


def prepare(client,h):
    visit_id=open_visit(client,h)
    water=CatalogItem(kind='product',name='隔离水',price=D(3),reference_code='test.water',stock_tracked=False)
    db.session.add(water);db.session.commit()
    add(client,h,visit_id,[('bath.scrub',1),('bath.cup',1),('test.water',1)])
    assert package(client,h,visit_id).status_code==200
    assert total(visit_id)==48
    return visit_id


@pytest.mark.parametrize('method',['cash','balance'])
def test_settlement_receipt_reports_and_reprint_use_net_once(client,formal_catalog,strict_owner_session,method):
    h=strict_owner_session['headers'];visit_id=prepare(client,h)
    member_id=None
    if method=='balance':
        created=client.post('/api/members',headers=h,json={'phone':'13800000001','name':'隔离会员'})
        assert created.status_code==201
        member_id=created.get_json()['data']['id']
        assert client.post(f'/api/members/{member_id}/recharge',headers=h,json={'amount':'100',
            'payment_method':'cash','idempotency_key':'fixture-recharge'}).status_code==200
    body={'visit_ids':[visit_id],'payments':[{'method':method,'amount':'48.00'}],
        'idempotency_key':'fixture-settlement','member_id':member_id}
    settled=client.post('/api/checkout',headers=h,json=body)
    assert settled.status_code==201,settled.get_json()
    settlement_id=settled.get_json()['data']['id']
    assert client.post('/api/checkout',headers=h,json=body).status_code==200
    receipt=client.get(f'/api/checkout/{settlement_id}/receipt',headers=h).get_json()['data']
    assert receipt['settlement']['total_amount']=='48.00'
    rows=receipt['visits'][0]['items']
    scrub=next(row for row in rows if row['name']=='搓澡')
    assert scrub['unit_price']=='10.00' and scrub['total_amount']=='0.00'
    assert D(scrub['covered_quantity'])==1
    assert scrub['included_amount']=='10.00'
    ranges={'start':'2026-01-01','end':'2027-01-01'}
    summary=client.get('/api/reports/summary',headers=h,query_string=ranges).get_json()['data']
    assert summary['operating_revenue']=='48.00'
    assert summary['actual_cash_inflow']==('100.00' if method=='balance' else '48.00')
    if member_id:
        assert db.session.get(Member,member_id).balance==52
        assert summary['stored_value_consumed']=='48.00'
    items=client.get('/api/reports/items',headers=h,query_string=ranges).get_json()['data']
    assert sum(D(row['amount']) for row in items if row['kind']=='package')==45
    assert sum(D(row['amount']) for row in items if row['kind']=='product')==3
    for _ in range(2):
        assert client.post(f'/api/checkout/{settlement_id}/print-result',headers=h,json={'success':True}).status_code==200
    assert Payment.query.count()==1 and Settlement.query.count()==1
    assert client.get(f'/api/checkout/{settlement_id}/receipt',headers=h).get_json()['data']['print_attempts']==2
    assert check_financial_integrity()['valid'] is True
    assert verify_audit_chain()==(True,None)


def test_wrong_net_formula_is_detected_and_identifies_the_order(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers'];visit_id=prepare(client,h)
    scrub=OrderItem.query.filter_by(visit_id=visit_id,catalog_item_id=item('bath.scrub').id,status='active').one()
    scrub.total_amount=D('0.01');db.session.commit()
    report=check_financial_integrity()
    assert report['valid'] is False
    assert any(row.get('code')=='ORDER_NET_MISMATCH' and row['entity_id']==scrub.id for row in report['issues'])


def test_self_consistent_but_forged_extra_inclusion_is_detected(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers'];visit_id=prepare(client,h)
    add(client,h,visit_id,[('bath.cup',1)],'extra-cup')
    parent=OrderItem.query.filter_by(visit_id=visit_id,kind='package',status='active').one()
    extra=OrderItem.query.filter_by(visit_id=visit_id,catalog_item_id=item('bath.cup').id,status='active',covered_quantity=0).one()
    extra.covered_quantity=D(1);extra.total_amount=D(0);extra.package_order_item_id=parent.id
    db.session.commit()
    report=check_financial_integrity()
    assert report['valid'] is False
    assert any(row.get('code')=='PACKAGE_COVERAGE_MISMATCH' and row['entity_id']==extra.id for row in report['issues'])


@pytest.mark.parametrize('mutation,code',[('snapshot','PACKAGE_SNAPSHOT_INVALID'),('quantity','PACKAGE_PARENT_INVALID'),
    ('duplicate','PACKAGE_PARENT_DUPLICATE')])
def test_package_parent_anomalies_are_located(client,formal_catalog,strict_owner_session,mutation,code):
    h=strict_owner_session['headers'];visit_id=prepare(client,h)
    parent=OrderItem.query.filter_by(visit_id=visit_id,kind='package',status='active').one()
    if mutation=='snapshot': parent.package_snapshot={}
    elif mutation=='quantity': parent.quantity=D(2);parent.total_amount=D(90)
    else:
        db.session.add(OrderItem(visit_id=visit_id,catalog_item_id=parent.catalog_item_id,kind='package',
            name_snapshot=parent.name_snapshot,unit_price=D(45),quantity=D(1),total_amount=D(45),
            created_by_id=strict_owner_session['owner_id'],package_snapshot=parent.package_snapshot))
    db.session.commit()
    report=check_financial_integrity()
    assert report['valid'] is False
    assert any(row.get('code')==code and row['entity_id']==parent.id for row in report['issues'])


def test_selected_linked_checkout_does_not_touch_other_package_or_settled_snapshot(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']
    bands=[Wristband.query.filter_by(number=n,is_active=True).one() for n in ['001','051']]
    linked=client.post('/api/wristbands/link-batch',headers=h,json={'wristband_ids':[band.id for band in bands]})
    assert linked.status_code==200
    a,b=[Visit.query.filter_by(wristband_id=band.id,status='open').one() for band in bands]
    assert package(client,h,a.id).status_code==200
    assert package(client,h,b.id,'B','packageB').status_code==200
    a_parent=OrderItem.query.filter_by(visit_id=a.id,kind='package',status='active').one()
    before=a_parent.package_snapshot
    response=client.post('/api/checkout',headers=h,json={'visit_ids':[a.id],'checkout_scope':'selected',
        'payments':[{'method':'cash','amount':'45'}],'idempotency_key':'separate'})
    assert response.status_code==201,response.get_json()
    assert a.status=='closed' and b.status=='open'
    assert total(b.id)==48
    assert package(client,h,a.id,'B','closed').status_code==409
    assert client.patch(f'/api/catalog/{item("package.A").id}',headers=h,json={'price':'99'}).status_code==200
    assert a_parent.unit_price==45 and a_parent.package_snapshot==before
    assert check_financial_integrity()['valid'] is True
