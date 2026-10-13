from datetime import datetime, timezone

import pytest

from app.api.errors import ApiError
from app.extensions import db
from app.models import OrderItem
from receipt_fixture050 import order, settle


def test_automatic_retry_never_prints_twice_and_results_are_idempotent(client, strict_owner_session, desktop050_employee_session):
    from app.receipt_models import ServicePrintJob
    result = order(client,strict_owner_session,desktop050_employee_session)
    job_id = result['response']['meta']['service_print_job']['id']
    path = '/api/service-print-jobs/'+job_id+'/attempts'
    headers = result['worker']['headers']
    body = {'request_key':'automatic-one','mode':'automatic'}
    first = client.post(path,headers=headers,json=body)
    assert first.status_code == 201 and first.get_json()['data']['print_allowed'] is True
    second = client.post(path,headers=headers,json=body)
    assert second.status_code == 200 and second.get_json()['data']['print_allowed'] is False
    alternate = client.post(path,headers=headers,json={'request_key':'automatic-two','mode':'automatic'})
    assert alternate.status_code == 200 and alternate.get_json()['data']['print_allowed'] is False
    attempt = first.get_json()['data']['id']
    saved = client.post(path+'/'+attempt+'/result',headers=headers,json={'success':False,'error':'打印机离线'})
    assert saved.status_code == 200
    repeated = client.post(path+'/'+attempt+'/result',headers=headers,json={'success':False,'error':'打印机离线'})
    assert repeated.status_code == 200
    assert db.session.get(ServicePrintJob,job_id).attempts == 1
    assert db.session.get(ServicePrintJob,job_id).status == 'failed'
    conflict = client.post(path+'/'+attempt+'/result',headers=headers,json={'success':True})
    assert conflict.status_code == 409
    assert OrderItem.query.filter_by(visit_id=result['visit'].id,status='active').count() == 2
    manual = client.post(path,headers=headers,json={'request_key':'manual-one','mode':'manual'})
    assert manual.status_code == 201 and manual.get_json()['data']['print_allowed'] is True


def test_beijing_day_boundaries_reject_at_next_midnight():
    from app.receipt_retention import business_day_bounds, next_midnight, require_current_receipt
    now = datetime(2026,10,10,16,0,tzinfo=timezone.utc)
    start,end = business_day_bounds(now)
    assert start == now and end == datetime(2026,10,11,16,0,tzinfo=timezone.utc)
    created = datetime(2026,10,10,15,59,59,tzinfo=timezone.utc)
    assert next_midnight(created) == now
    from types import SimpleNamespace
    with pytest.raises(ApiError) as error:
        require_current_receipt(SimpleNamespace(created_at=created),now)
    assert error.value.status == 410 and error.value.code == 'RECEIPT_EXPIRED'


@pytest.mark.parametrize('body', [None, [], {}, {'request_key':123,'mode':'automatic'},
    {'request_key':'a','mode':[]}, {'request_key':'a','mode':{}},
    {'request_key':'a','mode':'manual','snapshot':{}}, {'request_key':'x'*101,'mode':'manual'}])
def test_invalid_attempt_inputs_do_not_print_or_crash(client, strict_owner_session, desktop050_employee_session, body):
    result = order(client,strict_owner_session,desktop050_employee_session)
    job_id = result['response']['meta']['service_print_job']['id']
    response = client.post('/api/service-print-jobs/'+job_id+'/attempts',
                           headers=result['worker']['headers'],json=body)
    assert response.status_code == 400


def test_attempt_ids_cannot_cross_jobs_or_types(client, strict_owner_session, desktop050_employee_session):
    result = order(client,strict_owner_session,desktop050_employee_session)
    job_id = result['response']['meta']['service_print_job']['id']
    settlement = settle(client,strict_owner_session,result['visit'])
    path = '/api/service-print-jobs/'+job_id+'/attempts'
    attempt = client.post(path,headers=strict_owner_session['headers'],
        json={'request_key':'admin-service','mode':'manual'}).get_json()['data']['id']
    foreign = client.post('/api/checkout/'+settlement+'/print-attempts/'+attempt+'/result',
        headers=strict_owner_session['headers'],json={'success':True})
    assert foreign.status_code == 404
    foreign_actor = client.post(path+'/'+attempt+'/result',headers=result['worker']['headers'],json={'success':True})
    assert foreign_actor.status_code == 403


def test_settlement_attempt_does_not_change_money_or_duplicate_counter(client, strict_owner_session, desktop050_employee_session):
    from app.models import PrintJob, Settlement
    result = order(client,strict_owner_session,desktop050_employee_session,'cashier')
    settlement_id = settle(client,strict_owner_session,result['visit'])
    path = '/api/checkout/'+settlement_id+'/print-attempts'
    headers = result['worker']['headers']
    first = client.post(path,headers=headers,json={'request_key':'settlement-one','mode':'manual'})
    assert first.status_code == 201
    attempt_id = first.get_json()['data']['id']
    for _ in range(2):
        saved = client.post(path+'/'+attempt_id+'/result',headers=headers,json={'success':True})
        assert saved.status_code == 200
    assert PrintJob.query.filter_by(settlement_id=settlement_id).one().attempts == 1
    assert db.session.get(Settlement,settlement_id).status == 'completed'
