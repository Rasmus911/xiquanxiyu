from flask_jwt_extended import decode_token


def _create_mobile_employee(client, admin_headers):
    response = client.post(
        "/api/employees",
        json={
            "username": "mobile-session-worker",
            "display_name": "移动会话员工",
            "password": "staff123",
            "role": "male_scrubber",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def _mobile_login(client):
    terminal = client.post(
        "/api/terminals/register",
        json={"code": "MOBILE-SESSION-01", "name": "员工手机"},
    )
    assert terminal.status_code == 201
    response = client.post(
        "/api/auth/login",
        json={
            "username": "mobile-session-worker",
            "password": "staff123",
            "terminal_code": "MOBILE-SESSION-01",
        },
    )
    assert response.status_code == 200
    return response.get_json()["data"]


def test_mobile_refresh_token_expires_within_seven_days(app, client, admin_session):
    _create_mobile_employee(client, admin_session["headers"])
    login = _mobile_login(client)

    with app.app_context():
        payload = decode_token(login["refresh_token"])

    assert 604790 <= payload["exp"] - payload["iat"] <= 604810


def test_password_change_revokes_old_access_and_refresh_tokens(client, admin_session):
    employee = _create_mobile_employee(client, admin_session["headers"])
    login = _mobile_login(client)
    changed = client.patch(
        f"/api/employees/{employee['id']}",
        json={"password": "staff456"},
        headers=admin_session["headers"],
    )
    assert changed.status_code == 200

    old_access = client.get(
        "/api/mobile/bootstrap",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert old_access.status_code == 401
    assert old_access.get_json()["error"]["code"] == "SESSION_REVOKED"

    old_refresh = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {login['refresh_token']}"},
    )
    assert old_refresh.status_code == 401
    assert old_refresh.get_json()["error"]["code"] == "SESSION_REVOKED"


def test_disabled_terminal_rejects_existing_access_token(client, admin_session):
    _create_mobile_employee(client, admin_session["headers"])
    login = _mobile_login(client)
    terminals = client.get("/api/terminals", headers=admin_session["headers"]).get_json()["data"]
    terminal = next(row for row in terminals if row["code"] == "MOBILE-SESSION-01")
    disabled = client.patch(
        f"/api/terminals/{terminal['id']}",
        json={"is_active": False},
        headers=admin_session["headers"],
    )
    assert disabled.status_code == 200

    response = client.get(
        "/api/mobile/bootstrap",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "TERMINAL_DISABLED"
