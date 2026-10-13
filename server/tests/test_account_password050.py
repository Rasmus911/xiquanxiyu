"""Self-service changes never delegate identity and revoke all old sessions."""
import json

import pytest

from app.audit_service import verify_audit_chain
from app.extensions import db, socketio
from app.models import AuditLog, Employee


def payload(session, **changes):
    return {'old_password': session['password'], 'new_password': 'new-isolated-password-2026',
            'confirm_password': 'new-isolated-password-2026', **changes}


@pytest.mark.parametrize('role', ['male_scrubber', 'female_scrubber', 'floor_attendant',
                                 'cashier', 'inventory', 'manager', 'admin'])
def test_self_change_invalidates_both_old_tokens_and_socket(app, client, strict_owner_session,
                                                           desktop050_employee_session, role):
    session = (dict(strict_owner_session, id=strict_owner_session['owner_id'], username='fixture-owner')
               if role == 'admin' else desktop050_employee_session(role))
    employee = db.session.get(Employee, session['id'])
    original_version = employee.session_version
    connection = socketio.test_client(app, auth={'token': session['login']['access_token']})
    assert connection.is_connected()
    response = client.post('/api/auth/change-password', headers=session['headers'], json=payload(session))
    assert response.status_code == 200
    assert response.get_json()['data'] == {'relogin_required': True}
    assert client.get('/api/auth/me', headers=session['headers']).status_code == 401
    assert client.post('/api/auth/refresh', headers={
        'Authorization': 'Bearer ' + session['login']['refresh_token']}).status_code == 401
    assert not connection.is_connected()
    assert db.session.get(Employee, session['id']).session_version == original_version + 1
    login = {'username': session['username'], 'terminal_code':'ENTRY-TEST', 'client_channel':'desktop'}
    assert client.post('/api/auth/login', json={**login, 'password':session['password']}).status_code == 401
    logged = client.post('/api/auth/login', json={**login, 'password':payload(session)['new_password']})
    assert logged.status_code == 200
    state = logged.get_json()['data']['business_state']
    assert 'account-password' in state['ui_pages']
    assert state['capabilities']['account_password_change'] is True
    if role in {'male_scrubber', 'female_scrubber', 'floor_attendant'}:
        assert 'employees' not in state['ui_pages']
    audits = AuditLog.query.filter_by(action='account.password_change').all()
    assert len(audits) == 1 and audits[0].employee_id == session['id']
    encoded = json.dumps(audits[0].details, ensure_ascii=False)
    assert session['password'] not in encoded and payload(session)['new_password'] not in encoded
    assert verify_audit_chain() == (True, None)


@pytest.mark.parametrize('body', [None, [], 'string', {},
    {'old_password':'old', 'new_password':'new'},
    {'old_password':'old', 'new_password':'new', 'confirm_password':'new', 'employee_id':'other'},
    {'old_password':None, 'new_password':'new', 'confirm_password':'new'},
    {'old_password':'old', 'new_password':123456789, 'confirm_password':'new'},
    {'old_password':'old', 'new_password':'new', 'confirm_password':False}])
def test_invalid_fields_cannot_change_or_target_account(client, desktop050_employee_session, body):
    session = desktop050_employee_session()
    before = db.session.get(Employee, session['id']).password_hash
    response = client.post('/api/auth/change-password', headers=session['headers'], json=body)
    assert response.status_code == 400
    assert db.session.get(Employee, session['id']).password_hash == before


@pytest.mark.parametrize('changes,code', [
    ({'confirm_password':'different-password'}, 'PASSWORD_CONFIRM_MISMATCH'),
    ({'new_password':'isolated-employee-password-2026',
      'confirm_password':'isolated-employee-password-2026'}, 'PASSWORD_UNCHANGED'),
    ({'new_password':'short','confirm_password':'short'}, 'WEAK_PASSWORD'),
    ({'new_password':'x'*129,'confirm_password':'x'*129}, 'WEAK_PASSWORD'),
])
def test_invalid_new_password_keeps_current_session(client, desktop050_employee_session, changes, code):
    session = desktop050_employee_session()
    result = client.post('/api/auth/change-password', headers=session['headers'], json=payload(session, **changes))
    assert result.status_code == 400
    assert result.get_json()['error']['code'] == code
    assert client.get('/api/auth/me', headers=session['headers']).status_code == 200


def test_wrong_old_password_locks_after_five_attempts(client, desktop050_employee_session):
    session = desktop050_employee_session()
    for _ in range(5):
        result = client.post('/api/auth/change-password', headers=session['headers'],
                             json=payload(session, old_password='wrong-password'))
        assert result.status_code == 403
        assert result.get_json()['error']['code'] == 'REAUTH_FAILED'
    assert client.post('/api/auth/change-password', headers=session['headers'],
                       json=payload(session)).status_code == 423
    assert AuditLog.query.filter_by(action='account.password_change').count() == 0
