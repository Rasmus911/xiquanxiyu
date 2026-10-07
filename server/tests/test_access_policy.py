"""Strict policy tests use only the isolated TestConfig database."""
import pytest
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token

from app.auth_service import hash_password
from app.extensions import db
from app.models import AccessPolicyModel, BusinessPeriod, BusinessStateModel, Employee, Terminal, new_uuid


@pytest.fixture()
def accounts(app):
    app.config['ACCESS_POLICY_LEGACY_COMPAT'] = False
    password_hash = hash_password('sample-only-1234')
    rows = [Employee(username=name, display_name=name, role='admin',
                     password_hash=password_hash)
            for name in ('于在跃', '于景辉', '李丽娜', '其他员工')]
    db.session.add_all([*rows, Terminal(code='TEST-01', name='测试终端')])
    db.session.commit()
    return [row.id for row in rows]


@pytest.fixture()
def bound_owner_accounts(accounts):
    # Install the approved persisted shape directly to test the currently missing
    # login boundary before the activation command exists.
    db.session.add(AccessPolicyModel(owner_id=accounts[0], mobile_employee_ids=accounts[1:3],
                                    policy_version=1, is_active=True))
    db.session.get(BusinessStateModel, 1).policy_version = 1
    db.session.commit()
    return accounts


def login(client, username='于在跃', channel='desktop', **extra):
    return client.post('/api/auth/login', json={
        'username': username, 'password': 'sample-only-1234',
        'terminal_code': 'TEST-01', 'client_channel': channel, **extra,
    })


def test_mobile_admin_cannot_request_desktop_login(client, bound_owner_accounts):
    response = login(client, '于景辉')
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'CHANNEL_FORBIDDEN'


@pytest.mark.parametrize('channel', ['desktop', 'web', 'mobile'])
def test_missing_policy_fails_closed(client, accounts, channel):
    response = login(client, channel=channel)
    assert response.status_code == 503
    assert response.get_json()['error']['code'] == 'ACCESS_POLICY_NOT_CONFIGURED'


@pytest.mark.parametrize('name,channel', [('李丽娜', 'web'), ('其他员工', 'mobile'),
                                         ('于在跃', ''), ('于在跃', 'unknown'),
                                         ('于在跃', []), ('于在跃', {})])
def test_invalid_binding_or_channel_rejected(client, bound_owner_accounts, name, channel):
    response = login(client, name, channel)
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'CHANNEL_FORBIDDEN'


def headers(data, **extra):
    return {'Authorization': f"Bearer {data['access_token']}",
            'X-Business-Period': db.session.get(BusinessStateModel, 1).period_id, **extra}


def test_tokens_and_response_bind_policy_channel_and_period(client, bound_owner_accounts):
    data = login(client, '于景辉', 'mobile').get_json()['data']
    for key in ('access_token', 'refresh_token'):
        payload = decode_token(data[key])
        assert payload['client_channel'] == 'mobile'
        assert payload['policy_version'] == 1
        assert payload['business_period_id'] == '00000000-0000-0000-0000-000000000001'
        assert set(payload['permission_scope']) == {
        'mobile:order', 'visit:package', 'report:read', 'inventory:read', 'inventory:write', 'catalog:read', 'catalog:write', 'catalog:layout'}
    assert data['permissions'] == sorted(decode_token(data['access_token'])['permission_scope'])
    assert data['business_state']['owner_reset_allowed'] is False


@pytest.mark.parametrize('path,method', [('/api/employees', 'get'), ('/api/settings', 'get'),
    ('/api/checkout', 'post'), ('/api/checkout/print-jobs', 'get')])
def test_mobile_scope_blocks_desktop_routes(client, bound_owner_accounts, path, method):
    data = login(client, '于景辉', 'mobile').get_json()['data']
    response = getattr(client, method)(path, headers=headers(data))
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'PERMISSION_DENIED'


def test_headers_and_terminal_prefix_cannot_upgrade_mobile(client, bound_owner_accounts):
    db.session.add(Terminal(code='DESKTOP-OWNER', name='伪造入口'))
    db.session.commit()
    data = login(client, '于景辉', 'mobile', terminal_code='DESKTOP-OWNER').get_json()['data']
    response = client.get('/api/employees', headers=headers(
        data, **{'X-Client-Channel': 'desktop', 'X-Access-Policy-Version': '999'}))
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'PERMISSION_DENIED'


def test_owner_mobile_has_reset_but_not_employee_permission(client, bound_owner_accounts):
    data = login(client, channel='mobile').get_json()['data']
    assert {'business:reset', 'business:archive'} <= set(data['permissions'])
    state = client.get('/api/business/state', headers=headers(data))
    assert state.status_code == 200
    assert state.get_json()['data']['owner_reset_allowed'] is True
    assert state.headers['X-Business-Period'] == '00000000-0000-0000-0000-000000000001'
    assert state.headers['X-Access-Policy-Version'] == '1'
    assert client.get('/api/employees', headers=headers(data)).status_code == 403


def test_missing_or_different_period_header_rejects_business_request(client, bound_owner_accounts):
    data = login(client).get_json()['data']
    for value in (None, new_uuid()):
        request_headers = headers(data)
        if value is None:
            request_headers.pop('X-Business-Period')
        else:
            request_headers['X-Business-Period'] = value
        response = client.get('/api/business/state', headers=request_headers)
        assert response.status_code == 409
        assert response.get_json()['error']['code'] == 'BUSINESS_PERIOD_CHANGED'


def test_old_jwt_and_previous_period_rejected(client, bound_owner_accounts):
    data = login(client).get_json()['data']
    payload = decode_token(data['access_token'])
    old = {key: value for key, value in payload.items()
           if key not in {'client_channel', 'permission_scope', 'policy_version', 'business_period_id'}}
    token = create_access_token(bound_owner_accounts[0], additional_claims=old)
    response = client.get('/api/business/state', headers=headers({'access_token': token}))
    assert response.status_code == 401
    assert response.get_json()['error']['code'] == 'SESSION_REVOKED'
    period = BusinessPeriod(id=new_uuid())
    db.session.add(period)
    db.session.flush()
    db.session.get(BusinessStateModel, 1).period_id = period.id
    db.session.commit()
    response = client.get('/api/business/state', headers=headers(data))
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'BUSINESS_PERIOD_CHANGED'


def test_refresh_retains_narrow_scope_and_ignores_requested_upgrade(client, bound_owner_accounts):
    data = login(client, '于景辉', 'mobile').get_json()['data']
    payload = decode_token(data['refresh_token'])
    payload['permission_scope'] = ['mobile:order']
    token = create_refresh_token(bound_owner_accounts[1], additional_claims=payload)
    response = client.post('/api/auth/refresh', headers={'Authorization': f'Bearer {token}'},
                           json={'client_channel': 'desktop', 'permission_scope': ['*']})
    assert response.status_code == 200
    data = response.get_json()['data']
    refreshed = decode_token(data['access_token'])
    assert refreshed['client_channel'] == 'mobile'
    assert refreshed['permission_scope'] == ['mobile:order']
    assert data['permissions'] == ['mobile:order']
    assert 'business_state' in data
    assert client.get('/api/mobile/management/report', headers=headers(data)).status_code == 403


def test_mobile_bootstrap_explicit_management_capabilities(client, bound_owner_accounts):
    for name in ('于在跃', '于景辉', '李丽娜'):
        data = login(client, name, 'mobile').get_json()['data']
        response = client.get('/api/mobile/bootstrap', headers=headers(data))
        assert response.status_code == 200
        assert all(response.get_json()['data']['employee']['capabilities'].values())


def test_activation_preserves_passwords_and_activation_states_revokes_sessions(client, accounts):
    from app.access_policy import activate_policy
    original = {row.id: row.password_hash for row in Employee.query.all()}
    versions = {row.id: row.session_version for row in Employee.query.all()}
    result = activate_policy(accounts[0], accounts[1:3])
    assert result['policy_version'] == 1
    assert db.session.get(BusinessStateModel, 1).policy_version == 1
    assert Employee.query.count() == 4
    for employee in Employee.query.all():
        assert employee.password_hash == original[employee.id]
        assert employee.is_active is True
        assert employee.session_version == versions[employee.id] + 1
        if employee.id in accounts[:3]:
            assert employee.role == 'admin' and employee.mobile_full_access
    data = login(client).get_json()['data']
    activate_policy(accounts[0], accounts[1:3])
    assert client.get('/api/business/state', headers=headers(data)).status_code == 401


@pytest.mark.parametrize('kind', ['duplicate', 'missing', 'invalid', 'disabled_owner'])
def test_invalid_activation_changes_nothing(accounts, kind):
    from app.access_policy import activate_policy
    owner = accounts[0]
    mobile = accounts[1:3]
    if kind == 'duplicate':
        mobile[0] = owner
    elif kind == 'missing':
        mobile[0] = new_uuid()
    elif kind == 'invalid':
        owner = '于在跃'
    else:
        db.session.get(Employee, owner).is_active = False
        db.session.commit()
    original = [(row.id, row.is_active, row.session_version) for row in Employee.query.all()]
    from app.api.errors import ApiError
    with pytest.raises(ApiError):
        activate_policy(owner, mobile)
    assert AccessPolicyModel.query.count() == 0
    assert db.session.get(BusinessStateModel, 1).policy_version == 0
    assert [(row.id, row.is_active, row.session_version) for row in Employee.query.all()] == original


def test_cli_preview_read_only_and_activate_uses_exact_ids(app, accounts):
    runner = app.test_cli_runner()
    result = runner.invoke(args=['access-policy', 'preview'])
    assert result.exit_code == 0
    for account in accounts:
        assert account in result.output
    assert 'password_hash' not in result.output and 'sample-only' not in result.output
    assert AccessPolicyModel.query.count() == 0
    result = runner.invoke(args=['access-policy', 'activate', '--owner-id', accounts[0],
        '--mobile-id', accounts[1], '--mobile-id', accounts[2]])
    assert result.exit_code == 0
    assert db.session.get(BusinessStateModel, 1).policy_version == 1


def test_new_same_name_admin_has_no_binding(client, bound_owner_accounts):
    original = db.session.get(Employee, bound_owner_accounts[0])
    original.username = 'original-owner'
    impostor = Employee(username='于在跃', display_name='于在跃', role='admin',
                        password_hash=original.password_hash, mobile_full_access=True)
    db.session.add(impostor)
    db.session.commit()
    response = login(client)
    assert response.status_code == 403
    original.display_name = '其他名字'
    db.session.commit()
    assert login(client, 'original-owner').status_code == 200


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'ambiguous'])
def test_corrupt_persisted_policy_fails_closed(client, bound_owner_accounts, change):
    policy = AccessPolicyModel.query.one()
    if change == 'duplicate':
        policy.mobile_employee_ids = [bound_owner_accounts[0], bound_owner_accounts[1]]
    elif change == 'missing':
        policy.mobile_employee_ids = [new_uuid(), bound_owner_accounts[1]]
    else:
        db.session.add(AccessPolicyModel(owner_id=bound_owner_accounts[0],
            mobile_employee_ids=bound_owner_accounts[1:3], policy_version=2, is_active=True))
    db.session.commit()
    response = login(client)
    assert response.status_code == 503
    assert response.get_json()['error']['code'] == 'ACCESS_POLICY_NOT_CONFIGURED'


def test_production_cannot_enable_legacy_compat(app, client, accounts):
    app.config.update(PRODUCTION=True, ACCESS_POLICY_LEGACY_COMPAT=True)
    assert login(client).status_code == 503


def test_password_lockout_and_unknown_identity_do_not_disclose_policy(client, accounts):
    for _ in range(5):
        response = login(client, password='wrong-password')
        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'INVALID_CREDENTIALS'
        assert 'password_hash' not in response.get_data(as_text=True)
    response = login(client)
    assert response.status_code == 423
    assert response.get_json()['error']['code'] == 'ACCOUNT_LOCKED'
    response = login(client, 'not-an-account')
    assert response.status_code == 401
    assert response.get_json()['error']['code'] == 'INVALID_CREDENTIALS'


def test_disabled_employee_rejected_on_login_access_and_refresh(client, bound_owner_accounts):
    data = login(client, '于景辉', 'mobile').get_json()['data']
    db.session.get(Employee, bound_owner_accounts[1]).is_active = False
    db.session.commit()
    assert login(client, '于景辉', 'mobile').status_code == 401
    for method, path, token in [('get', '/api/business/state', data['access_token']),
                               ('post', '/api/auth/refresh', data['refresh_token'])]:
        response = getattr(client, method)(path, headers=headers({'access_token': token}))
        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'ACCOUNT_DISABLED'


def test_employee_endpoint_cannot_enable_unbound_or_disable_owner(client, bound_owner_accounts):
    data = login(client).get_json()['data']
    for employee_id, change in [(bound_owner_accounts[3], {'is_active': True}),
                               (bound_owner_accounts[0], {'is_active': False}),
                               (bound_owner_accounts[0], {'role': 'cashier'})]:
        response = client.patch(f'/api/employees/{employee_id}', headers=headers(data), json=change)
        assert response.status_code == 403
    response = client.post('/api/employees', headers=headers(data), json={
        'username': 'new-admin', 'display_name': '于在跃', 'role': 'admin',
        'password': 'sample-only-1234'})
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'PERMISSION_DENIED'
    assert Employee.query.filter_by(username='new-admin').count() == 0


def test_mobile_owner_scope_is_bounded_even_for_signed_enlarged_claims(client, bound_owner_accounts):
    data = login(client, channel='mobile').get_json()['data']
    payload = decode_token(data['refresh_token'])
    payload['permission_scope'].append('employee:read')
    refresh = create_refresh_token(bound_owner_accounts[0], additional_claims=payload)
    response = client.post('/api/auth/refresh', headers={'Authorization': f'Bearer {refresh}'})
    assert response.status_code == 200
    fresh = response.get_json()['data']
    assert 'employee:read' not in fresh['permissions']
    assert client.get('/api/employees', headers=headers(fresh)).status_code == 403


def test_socket_rejects_old_policy_and_old_period(app, client, bound_owner_accounts):
    from app.extensions import socketio
    data = login(client, '于景辉', 'mobile').get_json()['data']
    payload = decode_token(data['access_token'])
    for change in ({'policy_version': 0}, {'business_period_id': new_uuid()},
                   {'client_channel': 'desktop'}, {'permission_scope': ['*']}):
        token = create_access_token(bound_owner_accounts[1], additional_claims={**payload, **change})
        connection = socketio.test_client(app, auth={'token': token})
        assert not connection.is_connected()


def test_policy_activation_disconnects_open_sockets(app, client, bound_owner_accounts):
    from app.access_policy import activate_policy
    from app.extensions import socketio
    data = login(client).get_json()['data']
    connection = socketio.test_client(app, auth={'token': data['access_token']})
    assert connection.is_connected()
    activate_policy(bound_owner_accounts[0], bound_owner_accounts[1:3])
    assert not connection.is_connected()


def test_socket_broadcast_is_scoped_and_revalidates_revocation(app, client, bound_owner_accounts):
    from app.extensions import socketio
    owner = login(client).get_json()['data']
    mobile = login(client, '于景辉', 'mobile').get_json()['data']
    owner_socket = socketio.test_client(app, auth={'token': owner['access_token']})
    mobile_socket = socketio.test_client(app, auth={'token': mobile['access_token']})
    # A real catalog mutation must deliver a refresh event to both authorized
    # channels, and never a payload to an expired/revoked/old-period connection.
    catalog = client.get('/api/catalog', headers=headers(owner)).get_json()['data']
    item = catalog[0]
    response = client.patch(f"/api/catalog/{item['id']}", headers=headers(owner), json={'name': '新名称'})
    assert response.status_code == 200
    assert any(event['name'] == 'catalog.changed' for event in owner_socket.get_received())
    assert any(event['name'] == 'catalog.changed' for event in mobile_socket.get_received())
    db.session.get(Employee, bound_owner_accounts[1]).is_active = False
    db.session.commit()
    response = client.patch(f"/api/catalog/{item['id']}", headers=headers(owner), json={'name': '再次修改'})
    assert response.status_code == 200
    assert not mobile_socket.is_connected()
    owner_socket.disconnect()


def test_socket_mobile_does_not_receive_checkout_or_member_events(app, client, bound_owner_accounts):
    from app.access_policy import emit_business_event
    from app.extensions import socketio
    owner = login(client).get_json()['data']
    mobile = login(client, '于景辉', 'mobile').get_json()['data']
    owner_socket = socketio.test_client(app, auth={'token': owner['access_token']})
    mobile_socket = socketio.test_client(app, auth={'token': mobile['access_token']})
    emit_business_event('member.changed', {'member_id': 'private'})
    emit_business_event('checkout.completed', {'settlement_id': 'private'})
    assert {event['name'] for event in owner_socket.get_received()} == {'member.changed', 'checkout.completed'}
    assert mobile_socket.get_received() == []
    owner_socket.disconnect()
    mobile_socket.disconnect()


def test_multiworker_configuration_is_rejected():
    from app import create_app
    from app.config import TestConfig
    class UnsupportedConfig(TestConfig):
        API_WORKERS = 2
    with pytest.raises(RuntimeError, match='single'):
        create_app(UnsupportedConfig)


def test_protocol_headers_exposed_to_cross_origin_clients(client, bound_owner_accounts):
    data = login(client).get_json()['data']
    response = client.get('/api/business/state', headers=headers(data, Origin='https://localhost'))
    assert response.status_code == 200
    exposed = response.headers.get('Access-Control-Expose-Headers', '').lower()
    assert 'x-business-period' in exposed
    assert 'x-access-policy-version' in exposed


def test_mobile_login_rejects_role_without_bootstrap_permission(client, bound_owner_accounts):
    employee = db.session.get(Employee, bound_owner_accounts[1])
    employee.role = 'cashier'
    db.session.commit()
    response = login(client, '于景辉', 'mobile')
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'CHANNEL_FORBIDDEN'
    assert 'access_token' not in response.get_data(as_text=True)


def test_logout_disconnects_socket_immediately(app, client, bound_owner_accounts):
    from app.extensions import socketio
    data = login(client).get_json()['data']
    connection = socketio.test_client(app, auth={'token': data['access_token']})
    assert connection.is_connected()
    assert client.post('/api/auth/logout', headers=headers(data)).status_code == 200
    assert not connection.is_connected()


@pytest.mark.parametrize('change', ['period', 'policy', 'lock', 'expiry'])
def test_idle_socket_sweep_disconnects_invalid_sessions(app, client, bound_owner_accounts, change):
    from datetime import timedelta

    from app.access_policy import revalidate_sockets
    from app.extensions import socketio
    from app.models import utcnow
    data = login(client).get_json()['data']
    connection = socketio.test_client(app, auth={'token': data['access_token']})
    assert connection.is_connected()
    if change == 'period':
        period = BusinessPeriod(id=new_uuid())
        db.session.add(period)
        db.session.flush()
        db.session.get(BusinessStateModel, 1).period_id = period.id
    elif change == 'policy':
        db.session.get(BusinessStateModel, 1).policy_version += 1
    elif change == 'lock':
        db.session.get(Employee, bound_owner_accounts[0]).locked_until = utcnow() + timedelta(minutes=15)
    else:
        # Replace stored credential with a genuinely signed expired token to
        # exercise the sweep's JWT expiry check without sleeping for hours.
        payload = decode_token(data['access_token'])
        payload['exp'] = 1
        expired = create_access_token(bound_owner_accounts[0], additional_claims=payload)
        registry = app.extensions['access_policy_sockets']['clients']
        next(iter(registry.values()))['token'] = expired
    db.session.commit()
    revalidate_sockets()
    assert not connection.is_connected()


def test_socket_narrow_scope_and_refresh_token_cannot_receive_admin_data(app, client, bound_owner_accounts):
    from app.access_policy import emit_business_event
    from app.extensions import socketio
    data = login(client, '于景辉', 'mobile').get_json()['data']
    assert not socketio.test_client(app, auth={'token': data['refresh_token']}).is_connected()
    payload = decode_token(data['access_token'])
    payload['permission_scope'] = ['mobile:order']
    token = create_access_token(bound_owner_accounts[1], additional_claims=payload)
    connection = socketio.test_client(app, auth={'token': token})
    emit_business_event('inventory.changed', {'catalog_item_id': 'private'})
    assert connection.get_received() == []
    emit_business_event('visit.changed', {'visit_id': 'allowed'})
    assert [event['name'] for event in connection.get_received()] == ['visit.changed']
    connection.disconnect()


def test_cli_preview_reports_current_bindings_without_mutation(app, bound_owner_accounts):
    import json
    result = app.test_cli_runner().invoke(args=['access-policy', 'preview'])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data['policies'][0]['owner_id'] == bound_owner_accounts[0]
    assert data['policies'][0]['mobile_ids'] == bound_owner_accounts[1:3]
    assert db.session.get(BusinessStateModel, 1).policy_version == 1


def test_activation_rolls_back_all_changes_if_audit_insert_fails(accounts):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.access_policy import activate_policy
    db.session.connection().execute(text("""CREATE TRIGGER reject_policy_audit
        BEFORE INSERT ON audit_logs WHEN NEW.action = 'access_policy.activate'
        BEGIN SELECT RAISE(ABORT, 'test audit failure'); END"""))
    db.session.commit()
    original = [(row.id, row.is_active, row.session_version, row.role) for row in Employee.query.all()]
    with pytest.raises(IntegrityError):
        activate_policy(accounts[0], accounts[1:3])
    assert AccessPolicyModel.query.count() == 0
    assert db.session.get(BusinessStateModel, 1).policy_version == 0
    assert [(row.id, row.is_active, row.session_version, row.role) for row in Employee.query.all()] == original


def test_idle_watcher_observes_external_database_change(tmp_path):
    import time

    from sqlalchemy import update

    from app import create_app
    from app.access_policy import activate_policy
    from app.config import TestConfig
    from app.extensions import socketio
    from app.seed import seed_defaults

    class WatchedConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'watcher.sqlite').as_posix()}"
        ACCESS_POLICY_LEGACY_COMPAT = False
        SOCKETIO_POLICY_POLL_SECONDS = 0.02

    application = create_app(WatchedConfig)
    with application.app_context():
        db.create_all()
        seed_defaults()
        digest = hash_password('sample-only-1234')
        employees = [Employee(username=name, display_name=name, role='admin', password_hash=digest)
                     for name in ('于在跃', '于景辉', '李丽娜')]
        db.session.add_all([*employees, Terminal(code='TEST-01', name='test')])
        db.session.commit()
        activate_policy(employees[0].id, [row.id for row in employees[1:]])
        engine = db.engine
    data = login(application.test_client()).get_json()['data']
    connection = socketio.test_client(application, auth={'token': data['access_token']})
    assert connection.is_connected()
    # A separate connection models a maintenance command's committed update.
    # No API request or broadcast occurs after this update.
    with engine.begin() as external:
        external.execute(update(Employee).values(session_version=Employee.session_version + 1))
    deadline = time.monotonic() + 3
    while connection.is_connected() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not connection.is_connected()
    with application.app_context():
        db.session.remove()
        db.drop_all()
        engine.dispose()
