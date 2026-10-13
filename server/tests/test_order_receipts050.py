import pytest

from app.extensions import db
from app.models import IdempotencyRecord, OrderItem, PrintJob
from receipt_fixture050 import order


def test_batch_order_has_one_separate_job_on_retry(client, strict_owner_session, desktop050_employee_session):
    from app.receipt_models import ServicePrintJob
    submission = order(client,strict_owner_session,desktop050_employee_session)
    before_count = OrderItem.query.count()
    first = submission['response']
    second = client.post(submission['path'],headers=submission['headers'],json=submission['body']).get_json()
    assert first['meta']['service_print_job'] == second['meta']['service_print_job']
    assert ServicePrintJob.query.count() == 1 and PrintJob.query.count() == 0
    assert OrderItem.query.count() == before_count
    job = ServicePrintJob.query.one()
    snapshot = job.snapshot
    assert snapshot['wristband_number'] == '8001'
    assert snapshot['employee_username'] == submission['worker']['username']
    assert snapshot['receipt_kind'] == 'order'
    assert [row['name'] for row in snapshot['items']] == [submission['catalog'].name]
    record = IdempotencyRecord.query.filter_by(endpoint='visits:'+submission['visit'].id+':items:batch').one()
    assert 'snapshot' not in record.response_body and 'receipt' not in record.response_body


@pytest.mark.parametrize('role', ['cashier','inventory','manager'])
def test_non_service_order_never_requests_automatic_print(client, strict_owner_session, desktop050_employee_session, role):
    from app.receipt_models import ServicePrintJob
    result = order(client,strict_owner_session,desktop050_employee_session,role)
    assert not result['response'].get('meta')
    assert ServicePrintJob.query.count() == 0


def test_single_order_returns_same_reference_without_duplicate_order(client, strict_owner_session, desktop050_employee_session):
    from app.receipt_models import ServicePrintJob
    result = order(client,strict_owner_session,desktop050_employee_session)
    visit = result['visit']; db.session.refresh(visit)
    row = result['body']['items'][0]
    body = {**row,'version':visit.version}
    headers = {**result['worker']['headers'],'Idempotency-Key':'single-submission'}
    path = '/api/visits/'+visit.id+'/items'
    one = client.post(path,headers=headers,json=body)
    count = OrderItem.query.count()
    two = client.post(path,headers=headers,json=body)
    assert one.status_code == two.status_code == 201
    assert one.get_json()['meta'] == two.get_json()['meta']
    assert ServicePrintJob.query.count() == 2 and OrderItem.query.count() == count
