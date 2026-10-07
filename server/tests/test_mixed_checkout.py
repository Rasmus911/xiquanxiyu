from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Member, Payment, Settlement, StoredValueLedger, Visit
from app.audit_service import verify_audit_chain
from test_package_orders import open_visit


def prepare(client, headers):
    visit = open_visit(client, headers)
    member = client.post('/api/members', headers=headers, json={'phone':'13800000246','name':'组合收款会员'}).get_json()['data']
    assert client.post('/api/members/' + member['id'] + '/recharge', headers=headers,
        json={'amount':'10.00','payment_method':'cash','idempotency_key':'mix-recharge'}).status_code == 200
    return visit, member['id']


def test_mixed_checkout_consumes_partial_balance_once_and_receipt_report_refund_match(client, formal_catalog, strict_owner_session):
    h = strict_owner_session['headers']; visit, member = prepare(client,h)
    body = {'visit_ids':[visit], 'member_id':member, 'idempotency_key':'mixed-example',
        'payments':[{'method':'cash','amount':'2.00'},{'method':'alipay','amount':'3.00'},{'method':'balance','amount':'10.00'}]}
    result = client.post('/api/checkout', headers=h, json=body)
    assert result.status_code == 201, result.get_json()
    settlement = result.get_json()['data']['id']
    assert client.post('/api/checkout', headers=h, json=body).status_code == 200
    assert db.session.get(Member,member).balance == 0
    assert Settlement.query.count() == 1 and Payment.query.count() == 3
    assert StoredValueLedger.query.filter_by(entry_type='consume').count() == 1
    receipt = client.get('/api/checkout/' + settlement + '/receipt', headers=h).get_json()['data']
    assert receipt['settlement']['total_amount'] == '15.00'
    assert {p['method']:p['amount'] for p in receipt['payments']} == {'cash':'2.00','alipay':'3.00','balance':'10.00'}
    report = client.get('/api/reports/summary',headers=h,query_string={'start':'2026-01-01','end':'2027-01-01'}).get_json()['data']
    assert report['operating_revenue'] == '15.00' and report['stored_value_consumed'] == '10.00'
    assert report['actual_cash_inflow'] == '15.00'  # initial recharge 10 + new external receipt 5, not 25
    assert client.post('/api/checkout/' + settlement + '/refund',headers=h,
        json={'password':strict_owner_session['password'],'reason':'隔离测试'}).status_code == 200
    assert db.session.get(Member,member).balance == Decimal('10.00')
    assert verify_audit_chain() == (True,None)


def test_insufficient_mixed_balance_rolls_back_all_channels_and_retry_cannot_charge_twice(client,formal_catalog,strict_owner_session):
    h=strict_owner_session['headers']; visit,member=prepare(client,h)
    body={'visit_ids':[visit],'member_id':member,'idempotency_key':'mixed-retry',
        'payments':[{'method':'cash','amount':'4.00'},{'method':'balance','amount':'11.00'}]}
    denied=client.post('/api/checkout',headers=h,json=body)
    assert denied.status_code == 409 and denied.get_json()['error']['code'] == 'INSUFFICIENT_BALANCE'
    assert db.session.get(Member,member).balance == 10
    assert db.session.get(Visit,visit).status == 'open' and Payment.query.count() == 0
    body['payments']=[{'method':'cash','amount':'5.00'},{'method':'balance','amount':'10.00'}]
    body['idempotency_key']='mixed-corrected'
    assert client.post('/api/checkout',headers=h,json=body).status_code == 201
    assert client.post('/api/checkout',headers=h,json=body).status_code == 200
    body['payments']=[{'method':'cash','amount':'15.00'}]
    assert client.post('/api/checkout',headers=h,json=body).status_code == 409
    assert db.session.get(Member,member).balance == 0
    assert Payment.query.count() == 2 and Settlement.query.count() == 1


@pytest.mark.parametrize('payments', ['bad', {'method':'cash','amount':'15'}, [None], [1]])
def test_malformed_payment_rows_are_rejected_without_closing_visit(client,formal_catalog,strict_owner_session,payments):
    h = strict_owner_session['headers']; visit = open_visit(client,h)
    response = client.post('/api/checkout',headers=h,json={'visit_ids':[visit],'payments':payments,'idempotency_key':'bad-row'})
    assert response.status_code == 400
    assert db.session.get(Visit,visit).status == 'open'
    assert Settlement.query.count() == 0
