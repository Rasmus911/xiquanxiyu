"""Account edits invalidate only their target, never the authorizing cashier/admin."""
import pytest

from app.extensions import db
from app.models import AuditLog, BusinessStateModel, Employee


def create(client, session, **changes):
    body = {'username': 'fixture-cashier', 'display_name': '测试收银', 'role': 'cashier',
        'password': 'fixture-cashier-2026', 'allowed_channels': ['desktop', 'web'], 'is_active': True}
    body.update(changes)
    return client.post('/api/employees', headers=session['headers'], json=body)


def login(client, session, username='fixture-cashier', password='fixture-cashier-2026', channel='desktop'):
    return client.post('/api/auth/login', json={'username': username, 'password': password,
        'terminal_code': session['terminal_code'], 'client_channel': channel})


def test_create_enable_and_login_do_not_revoke_owner(client, strict_owner_session):
    owner = db.session.get(Employee, strict_owner_session['owner_id'])
    owner_version = owner.session_version
    response = create(client, strict_owner_session, is_active=False)
    assert response.status_code == 201
    employee_id = response.get_json()['data']['id']
    assert response.get_json()['data']['allowed_channels'] == ['desktop', 'web']
    response = client.patch('/api/employees/' + employee_id, headers=strict_owner_session['headers'],
        json={'is_active': True})
    assert response.status_code == 200
    assert response.get_json()['data']['is_active'] is True
    assert login(client, strict_owner_session).status_code == 200
    assert client.get('/api/business/state', headers=strict_owner_session['headers']).status_code == 200
    assert db.session.get(Employee, owner.id).session_version == owner_version
    assert db.session.get(BusinessStateModel, 1).policy_version == 1


def test_rejected_target_grant_does_not_look_like_session_revocation(client, strict_owner_session):
    response = create(client, strict_owner_session, allowed_channels=[], is_active=False)
    assert response.status_code == 201
    employee_id = response.get_json()['data']['id']
    response = client.patch('/api/employees/' + employee_id, headers=strict_owner_session['headers'], json={'is_active': True})
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'PERMISSION_DENIED'
    assert client.get('/api/business/state', headers=strict_owner_session['headers']).status_code == 200


def test_soft_delete_retains_identity_audit_and_invalidates_old_token(client, strict_owner_session):
    created = create(client, strict_owner_session)
    assert created.status_code == 201
    employee_id = created.get_json()['data']['id']
    session = login(client, strict_owner_session).get_json()['data']
    employee_headers = {'Authorization': 'Bearer ' + session['access_token'],
        'X-Business-Period': session['business_state']['period_id']}
    original = db.session.get(Employee, employee_id).password_hash
    response = client.delete('/api/employees/' + employee_id, headers=strict_owner_session['headers'])
    assert response.status_code == 200
    row = db.session.get(Employee, employee_id)
    assert row.deleted_at is not None and not row.is_active
    assert row.allowed_channels == [] and row.password_hash == original
    assert row.username == 'fixture-cashier'
    assert AuditLog.query.filter_by(action='employee.delete', entity_id=employee_id).count() == 1
    assert login(client, strict_owner_session).status_code == 401
    assert client.get('/api/business/state', headers=employee_headers).status_code == 401
    normal = client.get('/api/employees', headers=strict_owner_session['headers']).get_json()['data']
    assert employee_id not in {item['id'] for item in normal}
    deleted = client.get('/api/employees?deleted=only', headers=strict_owner_session['headers']).get_json()['data']
    assert [item['id'] for item in deleted] == [employee_id]
    assert 'password_hash' not in deleted[0]
    assert client.delete('/api/employees/' + employee_id, headers=strict_owner_session['headers']).status_code == 200
    assert AuditLog.query.filter_by(action='employee.delete', entity_id=employee_id).count() == 1
    assert client.patch('/api/employees/' + employee_id, headers=strict_owner_session['headers'], json={'is_active': True}).status_code == 409
    assert create(client, strict_owner_session).status_code == 409


def test_protected_admins_cannot_be_deleted_disabled_or_downgraded(client, strict_owner_session):
    for employee_id in [strict_owner_session['owner_id'], *strict_owner_session['administrator_ids']]:
        for method, payload in [('delete', None), ('patch', {'is_active': False}), ('patch', {'role': 'cashier'}),
                                ('patch', {'allowed_channels': []})]:
            response = getattr(client, method)('/api/employees/' + employee_id,
                headers=strict_owner_session['headers'], json=payload)
            assert response.status_code == 403
            assert response.get_json()['error']['code'] in {'OWNER_REQUIRED', 'PROTECTED_ACCOUNT'}
        assert db.session.get(Employee, employee_id).is_active


def test_role_change_revokes_only_target_sessions(client, strict_owner_session):
    created = create(client, strict_owner_session)
    assert created.status_code == 201
    employee_id = created.get_json()['data']['id']
    session = login(client, strict_owner_session).get_json()['data']
    versions = {row.id: row.session_version for row in Employee.query.all()}
    response = client.patch('/api/employees/' + employee_id, headers=strict_owner_session['headers'],
        json={'role': 'inventory', 'allowed_channels': ['desktop', 'mobile']})
    assert response.status_code == 200
    for row in Employee.query.all():
        assert row.session_version == versions[row.id] + (1 if row.id == employee_id else 0)
    headers = {'Authorization': 'Bearer ' + session['access_token'],
        'X-Business-Period': session['business_state']['period_id']}
    assert client.get('/api/business/state', headers=headers).status_code == 401
    assert client.get('/api/business/state', headers=strict_owner_session['headers']).status_code == 200
    assert db.session.get(BusinessStateModel, 1).policy_version == 1


@pytest.mark.parametrize('changes', [{'is_active': 'false'}, {'permission_scope': ['*']},
    {'mobile_full_access': True}, {'role': 'admin'}])
def test_creation_rejects_untrusted_security_fields_without_saving(client, strict_owner_session, changes):
    response = create(client, strict_owner_session, **changes)
    assert response.status_code in {400, 403}
    assert Employee.query.filter_by(username='fixture-cashier').count() == 0
