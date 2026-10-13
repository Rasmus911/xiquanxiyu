"""Deleted logins free usernames without rewriting historical responsibility."""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError

from app.audit_service import verify_audit_chain
from app.extensions import db
from app.models import AuditLog, Employee, RevokedSession, Visit, Wristband


def test_delete_releases_username_preserving_evidence(client, strict_owner_session,
                                                     desktop050_employee_session):
    first = desktop050_employee_session()
    before = [(row.id, row.current_hash) for row in AuditLog.query.order_by(AuditLog.chain_index)]
    response = client.delete('/api/employees/' + first['id'], headers=strict_owner_session['headers'])
    assert response.status_code == 200
    assert db.session.get(Employee, first['id']) is None
    second = desktop050_employee_session(username=first['username'])
    assert second['id'] != first['id']
    after = [(row.id, row.current_hash) for row in AuditLog.query.order_by(AuditLog.chain_index)]
    assert after[:len(before)] == before
    assert verify_audit_chain() == (True, None)
    assert client.get('/api/business/state', headers=first['headers']).status_code == 401
    assert client.post('/api/auth/refresh', headers={
        'Authorization': 'Bearer ' + first['login']['refresh_token']}).status_code == 401
    assert response.get_json()['data'] == {'id': first['id'], 'deleted': True}
    assert client.delete('/api/employees/' + first['id'], headers=strict_owner_session['headers']).status_code == 404


def test_history_and_revoked_sessions_survive_true_deletion(client, strict_owner_session,
                                                          desktop050_employee_session):
    worker = desktop050_employee_session()
    band = Wristband.query.filter_by(number='8001').one()
    opened = client.post('/api/wristbands/' + band.id + '/open', headers=worker['headers'], json={})
    assert opened.status_code == 201
    visit_id = opened.get_json()['data']['id']
    assert client.post('/api/auth/logout', headers=worker['headers']).status_code == 200
    revoked = [(r.id, r.employee_id) for r in RevokedSession.query.all()]
    assert client.delete('/api/employees/' + worker['id'], headers=strict_owner_session['headers']).status_code == 200
    assert db.session.get(Employee, worker['id']) is None
    assert db.session.get(Visit, visit_id).opened_by_id == worker['id']
    assert [(r.id, r.employee_id) for r in RevokedSession.query.all()] == revoked
    from app.employee_identity import historical_employee
    identity = historical_employee(worker['id'], db.session)
    assert identity.username == worker['username']
    assert not hasattr(identity, 'password_hash')
    assert verify_audit_chain() == (True, None)
    assert db.session.execute(text('PRAGMA foreign_key_check')).all() == []


def test_identity_is_not_an_account_and_is_append_only(client, desktop050_employee_session):
    worker = desktop050_employee_session()
    columns = {c['name'] for c in inspect(db.engine).get_columns('employee_identities')}
    assert columns == {'id', 'username', 'display_name', 'role', 'created_at'}
    for sql in ('UPDATE employee_identities SET username=\'tampered\' WHERE id=:id',
                'DELETE FROM employee_identities WHERE id=:id'):
        with pytest.raises(DatabaseError):
            db.session.execute(text(sql), {'id': worker['id']})
        db.session.rollback()


def test_deleted_registration_receipt_cannot_report_success_again(app, client, strict_owner_session):
    from app.registration_models import RegistrationReceipt
    app.config['REGISTRATION_TOKEN_SECRET'] = 'isolated-registration-secret-32-bytes-only'
    viewer = db.session.get(Employee, strict_owner_session['administrator_ids'][0])
    viewer.username = '18603346509'
    db.session.commit()
    logged = client.post('/api/auth/login', json={'username': viewer.username,
        'password': strict_owner_session['password'], 'terminal_code':'ENTRY-TEST', 'client_channel':'mobile'})
    assert logged.status_code == 200
    headers = {'Authorization': 'Bearer ' + logged.get_json()['data']['access_token'],
               'X-Business-Period': strict_owner_session['headers']['X-Business-Period']}
    def code():
        result = client.post('/api/auth/registration-token/current', headers=headers)
        assert result.status_code == 200
        return result.get_json()['data']['code']
    body = {'username':'13900001234', 'display_name':'隔离员工', 'role':'male_scrubber',
        'password':'isolated-staff-password', 'terminal_code':'ENTRY-TEST', 'client_channel':'desktop', 'code':code()}
    registered = client.post('/api/auth/register', json=body, headers={'Idempotency-Key':'first-account'})
    assert registered.status_code == 201
    first_id = registered.get_json()['data']['id']
    original_receipt = [(r.key, r.employee_id, r.identity) for r in RegistrationReceipt.query.all()]
    assert client.delete('/api/employees/' + first_id, headers=strict_owner_session['headers']).status_code == 200
    retry = client.post('/api/auth/register', json=body, headers={'Idempotency-Key':'first-account'})
    assert retry.status_code == 409
    assert retry.get_json()['error']['code'] == 'REGISTERED_ACCOUNT_REMOVED'
    assert [(r.key, r.employee_id, r.identity) for r in RegistrationReceipt.query.all()] == original_receipt
    body['code'] = code()
    replacement = client.post('/api/auth/register', json=body, headers={'Idempotency-Key':'new-account'})
    assert replacement.status_code == 201
    assert replacement.get_json()['data']['id'] != first_id
    assert verify_audit_chain() == (True, None)
