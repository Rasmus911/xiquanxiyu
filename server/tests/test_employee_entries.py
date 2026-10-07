"""Explicit channels must not elevate an unbound admin or widen a refreshed token."""
import pytest

from app.api.errors import ApiError
from app.extensions import db
from app.models import AccessPolicyModel, Employee


def test_persisted_entry_model_has_fail_closed_default(app):
    assert {'allowed_channels', 'deleted_at'} <= set(Employee.__table__.columns.keys())
    employee = Employee(username='no-grant', display_name='待授权', role='cashier', password_hash='fixture')
    db.session.add(employee)
    db.session.commit()
    assert employee.allowed_channels == []
    assert employee.deleted_at is None


@pytest.mark.parametrize('role,channels,want', [
    ('cashier', ['web', 'desktop'], ['desktop', 'web']),
    ('inventory', ['mobile'], ['mobile']),
    ('male_scrubber', ['mobile', 'desktop'], ['desktop', 'mobile']),
    ('female_scrubber', [], []),
    ('floor_attendant', ['web'], ['web']),
])
def test_channel_validation_normalizes_without_extra_grants(role, channels, want):
    from app.employee_access import validate_employee_channels
    assert validate_employee_channels(role, channels) == want


@pytest.mark.parametrize('role,channels', [
    ('cashier', ['mobile']), ('cashier', ['desktop', 'desktop']),
    ('inventory', 'mobile'), ('inventory', [True]), ('inventory', ['unknown']),
    ('admin', ['desktop']), ('unknown', []),
])
def test_channel_validation_rejects_untrusted_input(role, channels):
    from app.employee_access import validate_employee_channels
    with pytest.raises(ApiError):
        validate_employee_channels(role, channels)


def _ordinary(strict_owner_session, role, channels):
    owner = db.session.get(Employee, strict_owner_session['owner_id'])
    employee = Employee(username='fixture-' + role, display_name='测试员工', role=role,
        password_hash=owner.password_hash, allowed_channels=channels)
    db.session.add(employee)
    db.session.commit()
    return employee


@pytest.mark.parametrize('role,channel,pages,caps', [
    ('cashier', 'desktop', ['wristbands', 'members', 'print-jobs', 'catalog', 'inventory', 'reports'],
        {'visit_open': True, 'visit_order': True, 'checkout_write': True, 'catalog_layout': True}),
    ('inventory', 'desktop', ['wristbands', 'members', 'print-jobs', 'catalog', 'inventory', 'reports'],
        {'visit_order': True, 'inventory_write': True, 'checkout_write': True}),
    ('inventory', 'mobile', ['wristbands', 'inventory', 'reports'],
        {'visit_order': True, 'inventory_write': True, 'checkout_write': False}),
    ('male_scrubber', 'mobile', ['wristbands'],
        {'visit_open': False, 'visit_order': True, 'checkout_write': False}),
    ('female_scrubber', 'web', ['wristbands'],
        {'visit_manage': False, 'visit_order': True, 'inventory_write': False}),
    ('floor_attendant', 'desktop', ['wristbands'],
        {'visit_manage': False, 'visit_order': True, 'member_write': False}),
])
def test_real_login_emits_minimal_pages_and_capabilities(client, strict_owner_session, role, channel, pages, caps):
    employee = _ordinary(strict_owner_session, role, [channel])
    response = client.post('/api/auth/login', json={'username': employee.username,
        'password': strict_owner_session['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': channel})
    assert response.status_code == 200
    state = response.get_json()['data']['business_state']
    assert state['ui_pages'] == pages
    for key, want in caps.items():
        assert state['capabilities'][key] is want
    assert state['owner_reset_allowed'] is False


def test_role_admin_or_same_name_cannot_create_channel_authority(client, strict_owner_session):
    employee = _ordinary(strict_owner_session, 'admin', ['desktop', 'web', 'mobile'])
    employee.display_name = '于在跃'
    db.session.commit()
    for channel in ('desktop', 'web', 'mobile'):
        response = client.post('/api/auth/login', json={'username': employee.username,
            'password': strict_owner_session['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': channel})
        assert response.status_code == 403
        assert response.get_json()['error']['code'] == 'CHANNEL_FORBIDDEN'


def test_mobile_only_administrator_binding_does_not_allow_desktop(client, strict_owner_session):
    policy = AccessPolicyModel.query.filter_by(is_active=True).one()
    mobile_id = strict_owner_session['administrator_ids'][0]
    policy.administrator_employee_ids = policy.administrator_employee_ids[1:]
    db.session.commit()
    employee = db.session.get(Employee, mobile_id)
    response = client.post('/api/auth/login', json={'username': employee.username,
        'password': strict_owner_session['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'desktop'})
    assert response.status_code == 403


def test_business_state_uses_verified_channel_not_request_hint(client, strict_owner_session):
    response = client.get('/api/business/state?client_channel=mobile',
        headers={**strict_owner_session['headers'], 'X-Client-Channel': 'mobile'})
    assert response.status_code == 200
    state = response.get_json()['data']
    assert state['ui_pages'] == ['wristbands', 'members', 'print-jobs', 'catalog', 'inventory',
                                  'reports', 'audit', 'employees', 'settings']
    assert state['capabilities']['checkout_write'] is True


def test_bound_administrators_mobile_have_management_without_financial_frontdesk(client, strict_owner_session):
    for employee_id in [strict_owner_session['owner_id'], *strict_owner_session['administrator_ids']]:
        employee = db.session.get(Employee, employee_id)
        response = client.post('/api/auth/login', json={'username': employee.username,
            'password': strict_owner_session['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'})
        assert response.status_code == 200
        data = response.get_json()['data']
        assert data['business_state']['ui_pages'] == ['wristbands', 'inventory', 'reports']
        assert data['business_state']['capabilities']['visit_order'] is True
        assert data['business_state']['capabilities']['checkout_write'] is False
        assert '*' not in data['permissions']


def test_refresh_does_not_expand_the_ui_of_a_narrow_mobile_token(client, strict_owner_session):
    from flask_jwt_extended import create_refresh_token, decode_token
    response = client.post('/api/auth/login', json={'username': 'fixture-owner',
        'password': strict_owner_session['password'], 'terminal_code': 'ENTRY-TEST', 'client_channel': 'mobile'})
    claims = decode_token(response.get_json()['data']['refresh_token'])
    narrowed = {key: value for key, value in claims.items() if key not in {'sub', 'type', 'exp', 'iat', 'nbf', 'jti', 'fresh'}}
    narrowed['permission_scope'] = ['mobile:order']
    token = create_refresh_token(identity=strict_owner_session['owner_id'], additional_claims=narrowed)
    response = client.post('/api/auth/refresh', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['permissions'] == ['mobile:order']
    assert data['business_state']['ui_pages'] == ['wristbands']
    assert data['business_state']['capabilities']['inventory_write'] is False
