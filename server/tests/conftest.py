import os

import pytest

os.environ['PYTHON_DOTENV_DISABLED'] = '1'

from app import create_app
from app.config import TestConfig
from app.extensions import db
from legacy_seed import seed_legacy_defaults


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        # Existing regression scenarios deliberately exercise historical 120-band
        # databases. New formal behavior has its own empty/formal fixtures.
        seed_legacy_defaults()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def formal_catalog(app):
    # Explicit isolated fixture: never selects a configured cloud database.
    from app.operations_upgrade import apply_formal_catalog, retire_legacy_wristbands_and_create_hundred
    items = apply_formal_catalog(db.session)
    bands = retire_legacy_wristbands_and_create_hundred(db.session)
    db.session.commit()
    return {'items':items, 'bands':bands}


@pytest.fixture()
def admin_session(client):
    terminal = client.post("/api/terminals/register", json={"code": "TEST-01", "name": "测试终端"})
    assert terminal.status_code == 201
    bootstrap = client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "display_name": "管理员", "password": "admin123"},
    )
    assert bootstrap.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123", "terminal_code": "TEST-01"},
    )
    assert login.status_code == 200
    data = login.get_json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    return {"headers": headers, "login": data}


@pytest.fixture()
def strict_owner_session(app, client):
    from app.auth_service import hash_password
    from app.models import AccessPolicyModel, BusinessStateModel, Employee, Terminal

    app.config['ACCESS_POLICY_LEGACY_COMPAT'] = False
    password = 'fixture-only-password-2026'
    digest = hash_password(password)
    rows = [Employee(username=name, display_name=name, role='admin', password_hash=digest)
            for name in ('fixture-owner', 'fixture-a', 'fixture-b', 'fixture-c')]
    db.session.add_all([*rows, Terminal(code='ENTRY-TEST', name='隔离测试终端')])
    db.session.flush()
    ids = [row.id for row in rows]
    state = db.session.get(BusinessStateModel, 1)
    state.policy_version = 1
    db.session.add(AccessPolicyModel(owner_id=ids[0], mobile_employee_ids=ids[1:3],
        administrator_employee_ids=ids[1:], policy_version=1, is_active=True))
    db.session.commit()
    response = client.post('/api/auth/login', json={'username': 'fixture-owner',
        'password': password, 'terminal_code': 'ENTRY-TEST', 'client_channel': 'desktop'})
    assert response.status_code == 200
    data = response.get_json()['data']
    return {'owner_id': ids[0], 'administrator_ids': ids[1:], 'password': password,
        'headers': {'Authorization': f"Bearer {data['access_token']}",
                    'X-Business-Period': state.period_id}, 'terminal_code': 'ENTRY-TEST',
        'login': data}
