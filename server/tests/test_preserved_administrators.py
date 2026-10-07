"""Explicit existing-admin bindings; only an immutable owner ID may reset."""
import json

import pytest
from flask_jwt_extended import decode_token

from app.auth_service import hash_password
from app.extensions import db
from app.models import AccessPolicyModel, BusinessStateModel, Employee, Terminal, new_uuid


@pytest.fixture()
def existing_admins(app):
    app.config['ACCESS_POLICY_LEGACY_COMPAT'] = False
    digest = hash_password('test-admin-only-1234')
    rows = [Employee(username=username, display_name=name, password_hash=digest, role='admin')
            for username, name in [('于在跃', '系统管理员'), ('15133863898', '于景辉'),
                                   ('18603346509', '李丽娜'), ('18631459666', '于在跃')]]
    rows += [Employee(username='unbound-admin', display_name='于在跃', password_hash=digest, role='admin'),
             Employee(username='disabled-account', display_name='停用员工', password_hash=digest,
                      role='cashier', is_active=False)]
    db.session.add_all([*rows, Terminal(code='TEST-ADMINS', name='isolated test')])
    db.session.commit()
    return [row.id for row in rows]


def activate_existing(app, ids, administrator_ids=None):
    args = ['access-policy', 'activate', '--owner-id', ids[0],
            '--mobile-id', ids[1], '--mobile-id', ids[2]]
    for employee_id in ids[1:4] if administrator_ids is None else administrator_ids:
        args.extend(['--administrator-id', employee_id])
    return app.test_cli_runner().invoke(args=args)


def admin_login(client, username, channel):
    return client.post('/api/auth/login', json={
        'username': username, 'password': 'test-admin-only-1234',
        'terminal_code': 'TEST-ADMINS', 'client_channel': channel,
    })


def session_headers(data):
    return {'Authorization': f"Bearer {data['access_token']}",
            'X-Business-Period': data['business_state']['period_id']}


def test_cli_binds_four_existing_admins_without_changing_identities_or_activation(app, existing_admins):
    before = {row.id: (row.username, row.display_name, row.password_hash, row.is_active, row.role,
                       row.session_version) for row in Employee.query.all()}
    result = activate_existing(app, existing_admins)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['administrator_ids'] == existing_admins[1:4]
    assert Employee.query.count() == 6
    for row in Employee.query.all():
        assert (row.username, row.display_name, row.password_hash, row.is_active, row.role) == before[row.id][:5]
        assert row.session_version == before[row.id][5] + 1


@pytest.mark.parametrize('username', ['于在跃', '15133863898', '18603346509', '18631459666'])
@pytest.mark.parametrize('channel', ['desktop', 'web', 'mobile'])
def test_each_explicit_existing_admin_can_login_and_use_available_management(
        app, client, existing_admins, username, channel):
    result = activate_existing(app, existing_admins)
    assert result.exit_code == 0, result.output
    response = admin_login(client, username, channel)
    assert response.status_code == 200, response.get_json()
    data = response.get_json()['data']
    assert isinstance(data['permissions'], list) and data['permissions']
    assert data['business_state']['owner_reset_allowed'] is (username == '于在跃')
    if channel == 'mobile':
        assert '*' not in data['permissions']
        response = client.get('/api/mobile/bootstrap', headers=session_headers(data))
        assert response.status_code == 200
        assert all(response.get_json()['data']['employee']['capabilities'].values())
    else:
        assert client.get('/api/employees', headers=session_headers(data)).status_code == 200
        assert client.get('/api/settings', headers=session_headers(data)).status_code == 200


@pytest.mark.parametrize('username', ['15133863898', '18603346509', '18631459666'])
@pytest.mark.parametrize('channel', ['desktop', 'web', 'mobile'])
def test_other_admins_cannot_reset_even_with_desktop_wildcard(app, client, existing_admins, username, channel):
    result = activate_existing(app, existing_admins)
    assert result.exit_code == 0, result.output
    data = admin_login(client, username, channel).get_json()['data']
    for method, path in [('get', '/api/business/reset/preview'), ('post', '/api/business/reset/tasks'),
                         ('get', '/api/business/reset/tasks'), ('get', '/api/business/archives')]:
        response = getattr(client, method)(path, headers=session_headers(data), json={})
        assert response.status_code == 403, (path, response.get_json())
        assert response.get_json()['error']['code'] == 'OWNER_REQUIRED'


@pytest.mark.parametrize('kind', ['duplicate', 'owner_repeated', 'missing', 'disabled', 'invalid'])
def test_invalid_admin_binding_is_atomic_and_does_not_activate_other_accounts(app, existing_admins, kind):
    admin_ids = list(existing_admins[1:4])
    admin_ids[-1] = {'duplicate': admin_ids[0], 'owner_repeated': existing_admins[0],
                     'missing': new_uuid(), 'disabled': existing_admins[5], 'invalid': '于在跃'}[kind]
    before = [(row.id, row.is_active, row.role, row.session_version) for row in Employee.query.all()]
    result = activate_existing(app, existing_admins, admin_ids)
    assert result.exit_code != 0
    assert AccessPolicyModel.query.count() == 0
    assert db.session.get(BusinessStateModel, 1).policy_version == 0
    assert [(row.id, row.is_active, row.role, row.session_version) for row in Employee.query.all()] == before


def test_unbound_same_name_admin_is_preserved_but_never_granted_access(app, client, existing_admins):
    result = activate_existing(app, existing_admins)
    assert result.exit_code == 0, result.output
    assert db.session.get(Employee, existing_admins[4]).is_active
    for channel in ('desktop', 'web', 'mobile'):
        assert admin_login(client, 'unbound-admin', channel).status_code == 403


def test_admin_role_downgrade_removes_desktop_management(app, client, existing_admins):
    result = activate_existing(app, existing_admins)
    assert result.exit_code == 0, result.output
    data = admin_login(client, '18631459666', 'desktop').get_json()['data']
    employee = db.session.get(Employee, existing_admins[3])
    employee.role = 'cashier'
    db.session.commit()
    assert client.get('/api/employees', headers=session_headers(data)).status_code == 403
    assert admin_login(client, '18631459666', 'desktop').status_code == 403
    assert decode_token(data['access_token'])['sub'] == existing_admins[3]


def test_other_admin_cannot_replace_owner_password_to_bypass_reset_reauthentication(app, client, existing_admins):
    result = activate_existing(app, existing_admins)
    assert result.exit_code == 0, result.output
    data = admin_login(client, '18631459666', 'desktop').get_json()['data']
    owner = db.session.get(Employee, existing_admins[0])
    digest = owner.password_hash
    response = client.patch(f'/api/employees/{owner.id}', headers=session_headers(data),
                            json={'password': 'replacement-test-1234'})
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'OWNER_REQUIRED'
    assert db.session.get(Employee, owner.id).password_hash == digest
