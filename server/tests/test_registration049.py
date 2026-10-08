"""Shared authorization uses isolated strict-policy accounts, never real credentials."""
import pytest
from datetime import datetime, timedelta, timezone
import json
from contextlib import contextmanager

from app.extensions import db
from app.models import Employee


@pytest.fixture()
def app(tmp_path, request):
    from app import create_app
    from app.config import TestConfig
    from legacy_seed import seed_legacy_defaults

    file_database = request.node.name in {
        'test_concurrent_old_code_has_one_winner', 'test_restart_keeps_code_failures_and_receipt',
        'test_policy_rechecks_database_state_after_cached_employee',
    }

    class RegistrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = (f"sqlite:///{(tmp_path / 'registration.sqlite').as_posix()}"
                                   if file_database else 'sqlite://')

    application = create_app(RegistrationConfig)
    with application.app_context():
        db.create_all()
        seed_legacy_defaults()
        yield application
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def registration049_sessions(app, client, strict_owner_session):
    app.config['REGISTRATION_TOKEN_SECRET'] = 'isolated-registration-secret-32-bytes-only'
    ids = strict_owner_session['administrator_ids']
    # Preserve the policy mapping: the second required viewer is an additional
    # administrator, while the other mobile-bound administrator is not a viewer.
    for employee_id, username in zip(ids, ('18603346509', '15133863898', '18631459666')):
        db.session.get(Employee, employee_id).username = username
    db.session.commit()
    result = dict(strict_owner_session)
    for key, username in (('first', '18603346509'), ('second', '18631459666')):
        response = client.post('/api/auth/login', json={'username': username,
            'password': result['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'})
        assert response.status_code == 200
        result[key] = {'Authorization': 'Bearer ' + response.get_json()['data']['access_token'],
                       'X-Business-Period': result['headers']['X-Business-Period']}
    return result


def token(client, sessions):
    response = client.post('/api/auth/registration-token/current', headers=sessions['first'])
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    return response.get_json()['data']


def body(code, username='13900001234'):
    return dict(username=username, display_name='隔离员工', role='male_scrubber',
        password='fixture-staff-password', code=code, terminal_code='ENTRY-TEST', client_channel='desktop')


def register(client, data, key='registration-fixture-1', **kwargs):
    return client.post('/api/auth/register', json=data, headers={'Idempotency-Key': key}, **kwargs)


def test_same_token_and_single_use(app, client, registration049_sessions):
    first = token(client, registration049_sessions)
    second = client.post('/api/auth/registration-token/current',
                        headers=registration049_sessions['second']).get_json()['data']
    assert first['code'] == second['code']
    assert first['generation'] == second['generation']
    created = register(client, body(first['code']))
    assert created.status_code == 201
    assert created.get_json()['data']['allowed_channels'] == ['desktop']
    reused = register(client, body(first['code'], '13900001235'), 'registration-fixture-2')
    assert reused.status_code == 403


def test_expiry_boundary_and_success_reset(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(service, 'utcnow', lambda: start)
    first = token(client, registration049_sessions)
    monkeypatch.setattr(service, 'utcnow', lambda: start + timedelta(seconds=179))
    assert token(client, registration049_sessions)['code'] == first['code']
    assert register(client, body(first['code'])).status_code == 201
    rotated = token(client, registration049_sessions)
    assert rotated['code'] != first['code']
    assert rotated['generation'] == first['generation'] + 1
    assert datetime.fromisoformat(rotated['expires_at']) == start + timedelta(seconds=359)
    monkeypatch.setattr(service, 'utcnow', lambda: start + timedelta(seconds=359))
    expired = register(client, body(rotated['code'], '13900001235'), 'after-expiry')
    assert expired.status_code == 403
    assert expired.get_json()['error']['code'] == 'REGISTRATION_CODE_INVALID'


def test_exact_retry_and_changed_payload(app, client, registration049_sessions):
    first = token(client, registration049_sessions)
    data = body(first['code'])
    created = register(client, data)
    after = token(client, registration049_sessions)
    retried = register(client, data)
    assert retried.status_code == 201
    assert retried.get_json()['data'] == created.get_json()['data']
    assert token(client, registration049_sessions)['generation'] == after['generation']
    data['password'] = 'different-password'
    assert register(client, data).status_code == 409
    assert Employee.query.filter_by(username='13900001234').count() == 1


@pytest.mark.parametrize('field,value,status', [
    ('username', '１２９００００１２３４', 400), ('username', 13900001234, 400),
    ('display_name', ' ', 400), ('display_name', 'x' * 81, 400), ('display_name', None, 400),
    ('role', 'admin', 400), ('role', 'cashier', 400), ('password', 'short', 400),
    ('password', 'x' * 129, 400), ('password', [], 400), ('is_active', True, 400),
    ('allowed_channels', ['mobile'], 400), ('mobile_full_access', True, 400),
    ('client_channel', 'mobile', 403), ('client_channel', 'web', 403),
    ('terminal_code', 'not-registered', 403), ('code', '１２３４５６', 400),
])
def test_strict_registration_input(client, registration049_sessions, field, value, status):
    data = body(token(client, registration049_sessions)['code'])
    data[field] = value
    assert register(client, data).status_code == status
    assert Employee.query.filter_by(username='13900001234').first() is None


def test_duplicate_including_deleted_is_never_overwritten(app, client, registration049_sessions):
    from app.auth_service import hash_password
    original = Employee(username='13900001234', display_name='原账号', role='cashier',
        password_hash=hash_password('original-password'), deleted_at=datetime.now(timezone.utc))
    db.session.add(original)
    db.session.commit()
    employee_id, password_hash = original.id, original.password_hash
    first = token(client, registration049_sessions)
    assert register(client, body(first['code'])).status_code == 409
    assert db.session.get(Employee, employee_id).password_hash == password_hash
    assert token(client, registration049_sessions)['generation'] == first['generation']


def test_five_wrong_codes_survive_view_and_new_session(client, registration049_sessions):
    from app.registration_models import RegistrationTokenState
    first = token(client, registration049_sessions)
    wrong = '000000' if first['code'] != '000000' else '000001'
    for number in range(5):
        assert register(client, body(wrong), f'wrong-{number}').status_code == 403
        assert token(client, registration049_sessions)['generation'] == first['generation']
        db.session.remove()
    assert db.session.get(RegistrationTokenState, 1).wrong_attempts == 5
    limited = register(client, body(first['code']), 'after-five')
    assert limited.status_code == 429
    assert limited.get_json()['error']['code'] == 'REGISTRATION_RATE_LIMITED'


def test_sliding_terminal_and_source_limits(app, client, registration049_sessions, monkeypatch):
    from app.models import Terminal
    import app.registration_service as service
    db.session.add(Terminal(code='OTHER-TEST', name='第二隔离终端'))
    db.session.commit()
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(service, 'utcnow', lambda: start)
    for number in range(10):
        # Advance generations to avoid the independent five-wrong-codes gate.
        now = start + timedelta(seconds=number * 40)
        monkeypatch.setattr(service, 'utcnow', lambda: now)
        current = token(client, registration049_sessions)
        assert register(client, body(current['code'], f'1390000{number:04d}'), f'success-{number}').status_code == 201
    current = token(client, registration049_sessions)
    attempt = body(current['code'])
    attempt['terminal_code'] = 'OTHER-TEST'
    assert register(client, attempt, 'source-limited').status_code == 429
    attempt['terminal_code'] = 'ENTRY-TEST'
    assert register(client, attempt, 'terminal-limited', environ_overrides={'REMOTE_ADDR': '192.0.2.2'}).status_code == 429
    now = start + timedelta(seconds=600)
    monkeypatch.setattr(service, 'utcnow', lambda: now)
    current = token(client, registration049_sessions)
    assert register(client, body(current['code']), 'window-released').status_code == 201


@pytest.mark.parametrize('mutation', ['disabled', 'deleted', 'role', 'username', 'unbound', 'third', 'desktop'])
def test_view_policy_denies_invalid_identity(app, client, registration049_sessions, mutation):
    from app.models import AccessPolicyModel
    employee = db.session.get(Employee, registration049_sessions['administrator_ids'][0])
    headers = registration049_sessions['first']
    if mutation == 'disabled':
        employee.is_active = False
    elif mutation == 'deleted':
        employee.deleted_at = datetime.now(timezone.utc)
    elif mutation == 'role':
        employee.role = 'cashier'
    elif mutation == 'username':
        employee.username = 'fixture-renamed-nonviewer'
    elif mutation == 'unbound':
        policy = AccessPolicyModel.query.filter_by(is_active=True).one()
        policy.mobile_employee_ids = [registration049_sessions['administrator_ids'][2],
                                      registration049_sessions['administrator_ids'][1]]
        policy.administrator_employee_ids = registration049_sessions['administrator_ids'][1:]
    elif mutation == 'third':
        pass  # Existing third administrator keeps the disallowed exact username.
    elif mutation == 'desktop':
        headers = registration049_sessions['headers']
    db.session.commit()
    if mutation == 'third':
        third_login = client.post('/api/auth/login', json={'username': '15133863898',
            'password': registration049_sessions['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'})
        assert third_login.status_code == 200
        headers = {'Authorization': 'Bearer ' + third_login.get_json()['data']['access_token']}
    assert client.post('/api/auth/registration-token/current', headers=headers).status_code in (401, 403)


def test_capability_login_me_refresh_and_revocation(app, client, registration049_sessions):
    response = client.post('/api/auth/login', json={'username': '18603346509',
        'password': registration049_sessions['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'})
    data = response.get_json()['data']
    assert data['employee']['capabilities']['registration_token_view'] is True
    assert 'password_hash' not in data['employee']
    assert client.get('/api/auth/me', headers=registration049_sessions['first']).get_json()['data']['capabilities']['registration_token_view'] is True
    employee = db.session.get(Employee, registration049_sessions['administrator_ids'][0])
    employee.username = 'fixture-renamed-nonviewer'
    db.session.commit()
    refresh = client.post('/api/auth/refresh', headers={'Authorization': 'Bearer ' + data['refresh_token']})
    assert refresh.status_code == 200
    assert refresh.get_json()['data']['employee']['capabilities']['registration_token_view'] is False
    assert 'password_hash' not in refresh.get_json()['data']['employee']
    assert client.post('/api/auth/registration-token/current', headers=registration049_sessions['first']).status_code == 403


def test_secret_missing_and_maintenance(app, client, registration049_sessions):
    from app.models import BusinessStateModel
    first = token(client, registration049_sessions)
    app.config['REGISTRATION_TOKEN_SECRET'] = ''
    assert client.post('/api/auth/registration-token/current', headers=registration049_sessions['first']).status_code == 503
    assert register(client, body(first['code'])).get_json()['error']['code'] == 'REGISTRATION_NOT_CONFIGURED'
    assert client.get('/api/health').status_code == 200
    assert client.post('/api/auth/login', json={'username': '18603346509',
        'password': registration049_sessions['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'}).status_code == 200
    app.config['REGISTRATION_TOKEN_SECRET'] = 'isolated-registration-secret-32-bytes-only'
    db.session.get(BusinessStateModel, 1).maintenance = True
    db.session.commit()
    assert register(client, body(first['code'])).status_code == 503
    assert client.post('/api/auth/registration-token/current', headers=registration049_sessions['first']).status_code == 503


def test_safe_storage_view_dedup_and_desktop_only_permissions(app, client, registration049_sessions):
    from app.models import AuditLog
    from app.registration_models import RegistrationReceipt, RegistrationTokenState
    first = token(client, registration049_sessions)
    token(client, registration049_sessions)
    assert AuditLog.query.filter_by(action='registration.token_viewed').count() == 1
    data = body(first['code'])
    created = register(client, data)
    assert created.status_code == 201
    identity = created.get_json()['data']
    assert set(identity) == {'id', 'username', 'display_name', 'role', 'is_active', 'allowed_channels'}
    persisted = json.dumps([row.details for row in AuditLog.query.all()] +
        [row.identity for row in RegistrationReceipt.query.all()])
    assert data['password'] not in persisted and data['code'] not in persisted
    assert 'code' not in RegistrationTokenState.__table__.columns
    employee = Employee.query.filter_by(username=data['username']).one()
    assert employee.password_hash != data['password']
    for channel, status in [('desktop', 200), ('mobile', 403), ('web', 403)]:
        login = client.post('/api/auth/login', json={'username': data['username'], 'password': data['password'],
            'terminal_code': 'ENTRY-TEST', 'client_channel': channel})
        assert login.status_code == status
        if channel == 'desktop':
            assert set(login.get_json()['data']['permissions']) == {'visit:read', 'visit:order', 'mobile:order'}
            assert login.get_json()['data']['employee']['ui_pages'] == ['wristbands']
            assert login.get_json()['data']['employee']['capabilities']['registration_token_view'] is False


def test_concurrent_old_code_has_one_winner(app, client, registration049_sessions):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    first = token(client, registration049_sessions)
    db.session.remove()
    barrier = Barrier(2)

    def attempt(number):
        with app.app_context():
            with app.test_client() as other_client:
                barrier.wait(timeout=10)
                result = register(other_client, body(first['code'], f'1390000123{number}'), f'race-{number}')
                return result.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(attempt, (4, 5)))
    assert sorted(statuses) == [201, 403]
    assert Employee.query.filter(Employee.username.in_(['13900001234', '13900001235'])).count() == 1
    assert token(client, registration049_sessions)['generation'] == first['generation'] + 1


def test_restart_keeps_code_failures_and_receipt(app, client, registration049_sessions):
    from app import create_app
    from app.config import TestConfig
    first = token(client, registration049_sessions)
    wrong = '000000' if first['code'] != '000000' else '000001'
    assert register(client, body(wrong), 'pre-restart-wrong').status_code == 403
    db.session.remove()

    class RestartConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = app.config['SQLALCHEMY_DATABASE_URI']
        ACCESS_POLICY_LEGACY_COMPAT = False
        REGISTRATION_TOKEN_SECRET = app.config['REGISTRATION_TOKEN_SECRET']

    restarted = create_app(RestartConfig)
    with restarted.app_context():
        from app.registration_models import RegistrationTokenState
        with restarted.test_client() as restart_client:
            current = token(restart_client, registration049_sessions)
            assert current['code'] == first['code']
            assert current['generation'] == first['generation']
            assert current['expires_at'] == first['expires_at']
            assert db.session.get(RegistrationTokenState, 1).wrong_attempts == 1
            created = register(restart_client, body(first['code']))
            assert created.status_code == 201
        db.session.remove()
        db.engine.dispose()
    retried = register(client, body(first['code']))
    assert retried.status_code == 201
    assert retried.get_json()['data'] == created.get_json()['data']


def test_retry_after_expiry_does_not_mutate_generation(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    from app.registration_models import RegistrationTokenState
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(service, 'utcnow', lambda: start)
    first = token(client, registration049_sessions)
    created = register(client, body(first['code']))
    assert created.status_code == 201
    state = db.session.get(RegistrationTokenState, 1)
    generation, expires_at = state.generation, state.expires_at
    monkeypatch.setattr(service, 'utcnow', lambda: start + timedelta(seconds=181))
    assert register(client, body(first['code'])).get_json()['data'] == created.get_json()['data']
    db.session.expire_all()
    state = db.session.get(RegistrationTokenState, 1)
    assert state.generation == generation
    assert state.expires_at == expires_at


def test_revoked_session_and_username_spoof_are_denied(app, client, registration049_sessions):
    from app.registration_access import can_view_registration_token
    employee = Employee(username='18603346509', display_name='同名伪装', role='admin', is_active=True,
                        id='00000000-0000-0000-0000-000000000099')
    assert can_view_registration_token(employee, 'mobile') is False
    assert client.post('/api/auth/logout', headers=registration049_sessions['first']).status_code == 200
    assert client.post('/api/auth/registration-token/current', headers=registration049_sessions['first']).status_code == 401


def test_database_failure_rolls_back_employee_consumption_and_receipt(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    from app.registration_models import RegistrationReceipt
    first = token(client, registration049_sessions)
    original_audit = service.write_audit

    def failing_audit(action, *args, **kwargs):
        if action == 'registration.employee_created':
            raise RuntimeError('isolated commit failure')
        return original_audit(action, *args, **kwargs)

    monkeypatch.setattr(service, 'write_audit', failing_audit)
    assert register(client, body(first['code'])).status_code == 500
    assert Employee.query.filter_by(username='13900001234').first() is None
    assert RegistrationReceipt.query.count() == 0
    current = token(client, registration049_sessions)
    assert current['code'] == first['code'] and current['generation'] == first['generation']


def test_retry_is_terminal_bound_and_success_does_not_identify_approver(app, client, registration049_sessions):
    from app.models import Terminal, AuditLog
    db.session.add(Terminal(code='OTHER-TEST', name='隔离终端'))
    db.session.commit()
    data = body(token(client, registration049_sessions)['code'])
    assert register(client, data).status_code == 201
    data['terminal_code'] = 'OTHER-TEST'
    assert register(client, data).status_code == 409
    created_audit = AuditLog.query.filter_by(action='registration.employee_created').one()
    assert created_audit.employee_id is None
    assert created_audit.context['session_id'] is None
    assert created_audit.context['identity_verified'] is False
    assert created_audit.terminal_id is not None
    assert 'approver' not in created_audit.details
    consumed = AuditLog.query.filter_by(action='registration.token_rotated').one()
    assert consumed.employee_id is None
    assert consumed.terminal_id == created_audit.terminal_id


def test_view_and_default_audit_still_attribute_authenticated_actor(app, client, registration049_sessions):
    from app.models import AuditLog
    from app.audit_service import write_audit
    from flask_jwt_extended import verify_jwt_in_request
    token(client, registration049_sessions)
    view = AuditLog.query.filter_by(action='registration.token_viewed').one()
    employee_id = registration049_sessions['administrator_ids'][0]
    assert view.employee_id == employee_id
    assert view.context['session_id'] is not None
    assert view.context['identity_verified'] is True
    with app.test_request_context('/audit-default-fixture', headers=registration049_sessions['first']):
        verify_jwt_in_request()
        from app.auth_service import current_employee
        current_employee()
        record = write_audit('fixture.default_actor', 'employee', employee_id, {'isolated': True})
        db.session.commit()
        assert record.employee_id == employee_id
        assert record.context['identity_verified'] is True
        assert record.context['session_id'] is not None


def test_receipts_and_view_markers_are_immutable_sql(app, client, registration049_sessions):
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError
    data = body(token(client, registration049_sessions)['code'])
    assert register(client, data).status_code == 201
    for table in ('registration_receipts', 'registration_token_views'):
        for operation in (f'UPDATE {table} SET generation=generation+1', f'DELETE FROM {table}'):
            with pytest.raises(DatabaseError):
                db.session.execute(text(operation))
            db.session.rollback()


def test_wrong_code_budgets_expire_at_180(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(service, 'utcnow', lambda: start)
    first = token(client, registration049_sessions)
    wrong = '000000' if first['code'] != '000000' else '000001'
    for number in range(5):
        assert register(client, body(wrong), f'failure-{number}').status_code == 403
    monkeypatch.setattr(service, 'utcnow', lambda: start + timedelta(seconds=179))
    assert register(client, body(first['code']), 'blocked-before-expiry').status_code == 429
    monkeypatch.setattr(service, 'utcnow', lambda: start + timedelta(seconds=180))
    current = token(client, registration049_sessions)
    assert current['code'] != first['code']
    assert register(client, body(current['code']), 'after-expiry-budget').status_code == 201


def test_policy_rechecks_database_state_after_cached_employee(app, client, registration049_sessions):
    from sqlalchemy import text
    from app.registration_access import can_view_registration_token
    employee = db.session.get(Employee, registration049_sessions['administrator_ids'][0])
    assert employee.is_active
    with db.engine.begin() as connection:
        connection.execute(text('UPDATE employees SET is_active=FALSE WHERE id=:id'), {'id': employee.id})
    assert can_view_registration_token(employee, 'mobile') is False


def test_rotation_rejects_immediate_code_collision(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    from app.registration_models import RegistrationTokenState
    first = token(client, registration049_sessions)
    original = service.derive_code
    seeds = iter(('unused-insert-seed', 'collision-seed', 'replacement-seed'))

    def colliding_code(secret, generation, seed):
        if generation == first['generation'] + 1:
            return first['code'] if seed == 'collision-seed' else ('654321' if first['code'] != '654321' else '123456')
        return original(secret, generation, seed)

    with monkeypatch.context() as controlled:
        controlled.setattr(service.secrets, 'token_hex', lambda _length: next(seeds))
        controlled.setattr(service, 'derive_code', colliding_code)
        assert register(client, body(first['code'])).status_code == 201
    assert db.session.get(RegistrationTokenState, 1).seed == 'replacement-seed'


def test_retry_never_returns_privileges_from_a_forged_receipt(app, client, registration049_sessions):
    from sqlalchemy import text
    from app.registration_models import RegistrationReceipt
    data = body(token(client, registration049_sessions)['code'])
    assert register(client, data).status_code == 201
    receipt = RegistrationReceipt.query.one()
    key = receipt.key
    forged = dict(receipt.identity, role='admin', allowed_channels=['mobile'], access_token='forged-value')
    db.session.remove()
    # Deliberately emulate a corrupt backup in this disposable fixture. Runtime
    # SQL cannot normally rewrite receipts because the immutable trigger rejects it.
    with db.engine.begin() as connection:
        connection.exec_driver_sql('DROP TRIGGER protect_registration_receipts_update')
        connection.execute(text('UPDATE registration_receipts SET identity=:identity WHERE key=:key'),
                           {'identity': json.dumps(forged), 'key': key})
    result = register(client, data)
    assert result.status_code == 409
    assert 'data' not in result.get_json()


def test_protected_additional_administrator_views_same_token_without_policy_change(app, client, registration049_sessions):
    from app.models import AccessPolicyModel
    policy = AccessPolicyModel.query.filter_by(is_active=True).one()
    additional_id = registration049_sessions['administrator_ids'][2]
    before = (policy.owner_id, list(policy.mobile_employee_ids), list(policy.administrator_employee_ids),
              policy.policy_version)
    assert additional_id in policy.administrator_employee_ids
    assert additional_id not in policy.mobile_employee_ids
    response = client.post('/api/auth/login', json={'username': '18631459666',
        'password': registration049_sessions['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'})
    assert response.status_code == 200
    login = response.get_json()['data']
    assert login['employee']['capabilities']['registration_token_view'] is True
    first = token(client, registration049_sessions)
    second = client.post('/api/auth/registration-token/current', headers=registration049_sessions['second'])
    assert second.status_code == 200
    assert second.get_json()['data']['code'] == first['code']
    assert second.get_json()['data']['generation'] == first['generation']
    assert client.get('/api/auth/me', headers=registration049_sessions['second']).get_json()['data']['capabilities']['registration_token_view'] is True
    refreshed = client.post('/api/auth/refresh', headers={'Authorization': 'Bearer ' + login['refresh_token']})
    assert refreshed.status_code == 200
    assert refreshed.get_json()['data']['employee']['capabilities']['registration_token_view'] is True
    db.session.expire_all()
    policy = AccessPolicyModel.query.filter_by(is_active=True).one()
    assert (policy.owner_id, policy.mobile_employee_ids, policy.administrator_employee_ids, policy.policy_version) == before


@contextmanager
def clock_jump_after_singleton_lock(clock, acquired_at):
    """Advance test time at the real singleton lock query, without replacing locks."""
    from sqlalchemy import event
    engine = db.engine

    def lock_completed(_connection, _cursor, statement, _parameters, context, _executemany):
        compiled = context.compiled
        if (statement.lstrip().upper().startswith('SELECT') and 'registration_token_state' in statement
                and compiled is not None and getattr(compiled.statement, '_for_update_arg', None) is not None):
            clock[0] = acquired_at

    event.listen(engine, 'after_cursor_execute', lock_completed)
    try:
        yield
    finally:
        event.remove(engine, 'after_cursor_execute', lock_completed)


def test_lock_delayed_registration_rejects_expired_code_and_uses_current_rate_time(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    from app.registration_models import RegistrationRateLimit, RegistrationTokenState
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    clock = [start]
    monkeypatch.setattr(service, 'utcnow', lambda: clock[0])
    first = token(client, registration049_sessions)
    clock[0] = start + timedelta(seconds=179)
    with clock_jump_after_singleton_lock(clock, start + timedelta(seconds=180)):
        response = register(client, body(first['code']))
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'REGISTRATION_CODE_INVALID'
    assert Employee.query.filter_by(username='13900001234').first() is None
    state = db.session.get(RegistrationTokenState, 1)
    assert state.generation == first['generation'] + 1
    assert service._utc(state.expires_at) == start + timedelta(seconds=360)
    for rate in RegistrationRateLimit.query.all():
        assert rate.attempts == [(start + timedelta(seconds=180)).timestamp()]


def test_lock_delayed_view_rotates_expiry_and_returns_current_server_time(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    clock = [start]
    monkeypatch.setattr(service, 'utcnow', lambda: clock[0])
    first = token(client, registration049_sessions)
    clock[0] = start + timedelta(seconds=179)
    with clock_jump_after_singleton_lock(clock, start + timedelta(seconds=180)):
        current = token(client, registration049_sessions)
    assert current['generation'] == first['generation'] + 1
    assert current['code'] != first['code']
    assert datetime.fromisoformat(current['server_time']) == start + timedelta(seconds=180)
    assert datetime.fromisoformat(current['expires_at']) == start + timedelta(seconds=360)


def test_lock_delayed_exact_retry_preserves_generation_and_expiry(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    from app.registration_models import RegistrationTokenState
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    clock = [start]
    monkeypatch.setattr(service, 'utcnow', lambda: clock[0])
    data = body(token(client, registration049_sessions)['code'])
    created = register(client, data)
    assert created.status_code == 201
    current = db.session.get(RegistrationTokenState, 1)
    generation, expires_at = current.generation, current.expires_at
    clock[0] = start + timedelta(seconds=179)
    with clock_jump_after_singleton_lock(clock, start + timedelta(seconds=180)):
        retried = register(client, data)
    assert retried.status_code == 201
    assert retried.get_json()['data'] == created.get_json()['data']
    db.session.expire_all()
    current = db.session.get(RegistrationTokenState, 1)
    assert current.generation == generation and current.expires_at == expires_at


def test_lock_delayed_attempt_releases_old_rate_window(app, client, registration049_sessions, monkeypatch):
    import app.registration_service as service
    from app.registration_models import RegistrationRateLimit
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    clock = [start]
    monkeypatch.setattr(service, 'utcnow', lambda: clock[0])
    code = token(client, registration049_sessions)['code']
    wrong = '000000' if code != '000000' else '000001'
    assert register(client, body(wrong), 'prime-rate').status_code == 403
    for rate in RegistrationRateLimit.query.all():
        rate.attempts = [start.timestamp()] * 10
    db.session.commit()
    clock[0] = start + timedelta(seconds=599)
    current = token(client, registration049_sessions)
    with clock_jump_after_singleton_lock(clock, start + timedelta(seconds=600)):
        response = register(client, body(current['code']))
    assert response.status_code == 201
    for rate in RegistrationRateLimit.query.all():
        assert rate.attempts == [(start + timedelta(seconds=600)).timestamp()]
