import pytest

from receipt_fixture050 import order, settle


def test_worker_and_cashier_are_isolated_but_highest_admin_sees_both(client, strict_owner_session, desktop050_employee_session):
    result = order(client,strict_owner_session,desktop050_employee_session)
    job_id = result['response']['meta']['service_print_job']['id']
    settlement_id = settle(client,strict_owner_session,result['visit'])
    worker_headers = result['worker']['headers']
    cashier = desktop050_employee_session('cashier', username='13800000002')
    assert client.get('/api/service-print-jobs',headers=worker_headers).status_code == 200
    assert client.get('/api/checkout/print-jobs',headers=worker_headers).status_code == 403
    assert client.get('/api/checkout/'+settlement_id+'/receipt',headers=worker_headers).status_code == 403
    assert client.get('/api/service-print-jobs/'+job_id+'/receipt',headers=cashier['headers']).status_code == 403
    assert client.get('/api/checkout/print-jobs',headers=cashier['headers']).status_code == 200
    assert client.get('/api/service-print-jobs/'+job_id+'/receipt',headers=strict_owner_session['headers']).status_code == 200
    assert client.get('/api/checkout/'+settlement_id+'/receipt',headers=strict_owner_session['headers']).status_code == 200


def test_male_worker_cannot_read_female_slip_even_with_guessed_id(client, strict_owner_session, desktop050_employee_session):
    result = order(client,strict_owner_session,desktop050_employee_session,'female_scrubber','female')
    male = desktop050_employee_session('male_scrubber', username='13800000002')
    job_id = result['response']['meta']['service_print_job']['id']
    assert client.get('/api/service-print-jobs/'+job_id+'/receipt',headers=male['headers']).status_code == 403
    listing = client.get('/api/service-print-jobs',headers=male['headers']).get_json()['data']
    assert listing['items'] == [] and listing['total'] == 0


@pytest.mark.parametrize('role,area', [('male_scrubber','male'),('female_scrubber','female'),('floor_attendant','male')])
def test_service_login_has_only_order_receipts_not_settlement_permission(client, strict_owner_session, desktop050_employee_session,role,area):
    result = order(client,strict_owner_session,desktop050_employee_session,role,area)
    state = result['worker']['login']['business_state']
    assert 'print-jobs' in state['ui_pages']
    assert state['capabilities']['order_receipt_reprint'] is True
    assert state['capabilities']['receipt_reprint'] is False
