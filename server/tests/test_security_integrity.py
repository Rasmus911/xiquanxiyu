import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.audit_service import verify_audit_chain
from app.extensions import db
from app.models import AuditLog, Employee


def test_shared_clear_password_is_not_exposed(client, admin_session):
    rows = client.get("/api/settings", headers=admin_session["headers"]).get_json()["data"]
    assert not any(row["key"] == "force_clear_password" for row in rows)


def test_force_clear_requires_personal_password_and_reason(client, admin_session):
    headers = admin_session["headers"]
    band = client.get("/api/wristbands", headers=headers).get_json()["data"][0]
    client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers)
    old_password = client.post(
        f"/api/wristbands/{band['id']}/force-clear",
        json={"password": "00000000", "reason": "误开牌"},
        headers=headers,
    )
    assert old_password.status_code == 403
    missing_reason = client.post(
        f"/api/wristbands/{band['id']}/force-clear",
        json={"password": "admin123"},
        headers=headers,
    )
    assert missing_reason.status_code == 400
    valid = client.post(
        f"/api/wristbands/{band['id']}/force-clear",
        json={"password": "admin123", "reason": "误开牌"},
        headers=headers,
    )
    assert valid.status_code == 200


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "10000000000", "1.001"])
def test_recharge_rejects_nonfinite_overflow_and_fractional_cents(client, admin_session, value):
    headers = admin_session["headers"]
    member = client.post("/api/members", json={"phone": "13912345678"}, headers=headers).get_json()["data"]
    response = client.post(
        f"/api/members/{member['id']}/recharge",
        json={"amount": value, "payment_method": "cash"},
        headers={**headers, "Idempotency-Key": "invalid-money"},
    )
    assert response.status_code == 400
    assert client.get(f"/api/members/{member['id']}", headers=headers).get_json()["data"]["balance"] == "0.00"


def test_audit_keeps_original_identity_after_account_changes(app, client, admin_session):
    headers = admin_session["headers"]
    with app.app_context():
        employee = Employee.query.filter_by(username="admin").one()
        employee.username = "renamed-admin"
        db.session.commit()
    records = client.get("/api/audit", query_string={"action": "auth.login"}, headers=headers).get_json()["data"][
        "items"
    ]
    assert records[0]["employee_username"] == "admin"
    assert records[0]["integrity_version"] == 2
    assert records[0]["context"]["terminal_code"] == "TEST-01"
    assert records[0]["terminal_name"] == "测试终端"


def test_database_rejects_direct_audit_update_and_delete(app, admin_session):
    with app.app_context():
        with pytest.raises(DatabaseError):
            db.session.execute(text("UPDATE audit_logs SET created_at = '2000-01-01'"))
            db.session.commit()
        db.session.rollback()
        with pytest.raises(DatabaseError):
            db.session.execute(text("DELETE FROM audit_logs"))
            db.session.commit()
        db.session.rollback()
        assert verify_audit_chain() == (True, None)


def test_failed_login_is_traceable_without_recording_password(app, client, admin_session):
    response = client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "never-log-this-password",
            "terminal_code": "TEST-01",
        },
    )
    assert response.status_code == 401
    with app.app_context():
        record = AuditLog.query.filter_by(action="security.request_denied").one()
        assert record.context["employee_username"] == "admin"
        assert record.details["error_code"] == "INVALID_CREDENTIALS"
        assert "never-log-this-password" not in str(record.details) + str(record.context)


def test_logout_revokes_the_same_session_access_and_refresh(client, admin_session):
    headers = admin_session["headers"]
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    refresh = client.post(
        "/api/auth/refresh",
        headers={
            "Authorization": f"Bearer {admin_session['login']['refresh_token']}",
        },
    )
    assert refresh.status_code == 401


def test_anonymous_terminal_registration_cannot_rename_an_existing_device(client, admin_session):
    result = client.post("/api/terminals/register", json={"code": "TEST-01", "name": "冒名终端"})
    assert result.status_code == 201
    assert result.get_json()["data"]["name"] == "测试终端"


def test_evidence_export_contains_signed_checkpoint_and_matching_records(client, admin_session):
    response = client.get(
        "/api/audit/evidence", query_string={"action": "auth.login"}, headers=admin_session["headers"]
    )
    assert response.status_code == 200
    evidence = response.get_json()["data"]
    assert evidence["verification"]["valid"] is True
    assert evidence["checkpoint"]["chain_index"] >= 2
    assert len(evidence["signature"]) == 64
    assert evidence["records"][0]["context"]["employee_username"] == "admin"


def test_recharge_key_cannot_be_reused_for_different_amount(client, admin_session):
    headers = {**admin_session["headers"], "Idempotency-Key": "same-recharge"}
    member = client.post("/api/members", json={"phone": "13912345678"}, headers=headers).get_json()["data"]
    endpoint = f"/api/members/{member['id']}/recharge"
    body = {"amount": "100.00", "payment_method": "cash"}
    assert client.post(endpoint, json=body, headers=headers).status_code == 200
    assert client.post(endpoint, json=body, headers=headers).status_code == 200
    changed = client.post(endpoint, json={**body, "amount": "200.00"}, headers=headers)
    assert changed.status_code == 409
    assert changed.get_json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert client.get(f"/api/members/{member['id']}", headers=headers).get_json()["data"]["balance"] == "100.00"


def test_settled_amount_and_order_cannot_be_rewritten_but_refund_appends(client, admin_session, app):
    headers = admin_session["headers"]
    band = client.get("/api/wristbands", headers=headers).get_json()["data"][0]
    ticket = next(
        row for row in client.get("/api/catalog", headers=headers).get_json()["data"] if row["kind"] == "ticket"
    )
    client.patch(f"/api/catalog/{ticket['id']}", headers=headers, json={"price": "20.00"})
    opened = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers).get_json()["data"]
    visit_id = opened["id"]
    checkout = client.post(
        "/api/checkout",
        headers={**headers, "Idempotency-Key": "secure-checkout"},
        json={
            "visit_ids": [visit_id],
            "payments": [{"method": "cash", "amount": "20.00"}],
        },
    )
    assert checkout.status_code == 201
    settlement_id = checkout.get_json()["data"]["id"]
    reopened = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers).get_json()["data"]
    with app.app_context():
        for statement in (
            "UPDATE settlements SET total_amount = 1",
            "UPDATE order_items SET total_amount = 1",
            "DELETE FROM payments",
            "DELETE FROM settlement_visits",
        ):
            with pytest.raises(DatabaseError):
                db.session.connection().execute(text(statement))
                db.session.commit()
            db.session.rollback()
        with pytest.raises(DatabaseError):
            db.session.connection().execute(
                text("UPDATE order_items SET visit_id = :closed WHERE visit_id = :open"),
                {"closed": visit_id, "open": reopened["id"]},
            )
            db.session.commit()
        db.session.rollback()
    denied = client.post(f"/api/checkout/{settlement_id}/refund", headers=headers, json={"reason": "测试"})
    assert denied.status_code == 403
    refunded = client.post(
        f"/api/checkout/{settlement_id}/refund",
        headers=headers,
        json={
            "reason": "误收款退款",
            "password": "admin123",
        },
    )
    assert refunded.status_code == 200
    assert refunded.get_json()["data"]["total_amount"] == "20.00"
    with app.app_context():
        assert verify_audit_chain() == (True, None)


def test_financial_check_detects_balance_changed_outside_the_ledger(client, admin_session, app):
    headers = admin_session["headers"]
    member = client.post("/api/members", json={"phone": "13912345678"}, headers=headers).get_json()["data"]
    assert client.get("/api/audit/finance-integrity", headers=headers).get_json()["data"]["valid"] is True
    with app.app_context():
        db.session.connection().execute(text("UPDATE members SET balance = 888 WHERE id = :id"), {"id": member["id"]})
        db.session.commit()
    response = client.get("/api/audit/finance-integrity", headers=headers)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["valid"] is False
    assert data["issues"][0]["entity_id"] == member["id"]
    assert data["issues"][0]["kind"] == "member_balance"


def test_saved_checkpoint_is_checked_against_current_database(client, admin_session):
    headers = admin_session["headers"]
    document = client.get("/api/audit/evidence", headers=headers).get_json()["data"]
    checkpoint = document["checkpoint"]
    query = {"checkpoint_index": checkpoint["chain_index"], "checkpoint_hash": checkpoint["hash"]}
    assert (
        client.get("/api/audit/verify", headers=headers, query_string=query).get_json()["data"]["checkpoint_valid"]
        is True
    )
    query["checkpoint_hash"] = "f" * 64
    assert (
        client.get("/api/audit/verify", headers=headers, query_string=query).get_json()["data"]["checkpoint_valid"]
        is False
    )


def test_repeated_pass_consumption_uses_one_ledger_entry(client, admin_session):
    headers = admin_session["headers"]
    member = client.post("/api/members", headers=headers, json={"phone": "13912345678"}).get_json()["data"]
    card = client.post(
        f"/api/members/{member['id']}/passes",
        headers={**headers, "Idempotency-Key": "pass-issue"},
        json={"count": 2, "amount": "40.00", "payment_method": "cash"},
    ).get_json()["data"]
    endpoint = f"/api/members/passes/{card['id']}/consume"
    consume_headers = {**headers, "Idempotency-Key": "consume-once"}
    first = client.post(endpoint, json={}, headers=consume_headers)
    repeated = client.post(endpoint, json={}, headers=consume_headers)
    assert first.get_json()["data"]["remaining_count"] == 1
    assert repeated.get_json()["data"]["remaining_count"] == 1


def test_hmac_detects_privileged_timestamp_rewrite(app, admin_session):
    with app.app_context():
        db.session.execute(text("DROP TRIGGER protect_audit_logs_update"))
        db.session.execute(text("UPDATE audit_logs SET created_at='2000-01-01' WHERE chain_index=1"))
        db.session.commit()
        valid, broken_at = verify_audit_chain()
        assert valid is False
        assert broken_at == 1


def test_cashier_can_clear_bill_without_receiving_refund_authority(client, admin_session):
    headers = admin_session["headers"]
    employee = client.post(
        "/api/employees",
        headers=headers,
        json={
            "username": "cashier",
            "display_name": "测试收银员",
            "password": "cashier123",
            "role": "cashier",
        },
    )
    assert employee.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={
            "username": "cashier",
            "password": "cashier123",
            "terminal_code": "TEST-01",
        },
    ).get_json()["data"]
    band = client.get("/api/wristbands", headers=headers).get_json()["data"][0]
    client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers)
    cleared = client.post(
        f"/api/wristbands/{band['id']}/force-clear",
        headers={"Authorization": f"Bearer {login['access_token']}"},
        json={"password": "cashier123", "reason": "本人核对清空"},
    )
    assert cleared.status_code == 200
    denied = client.post('/api/checkout/unknown/refund',
        headers={"Authorization": f"Bearer {login['access_token']}"}, json={})
    assert denied.status_code == 403
    records = client.get(
        "/api/audit",
        headers=headers,
        query_string={
            "employee": "cashier",
            "action": "security.request_denied",
        },
    ).get_json()["data"]["items"]
    assert records[0]["context"]["identity_verified"] is True


def test_client_forged_price_is_ignored(client, admin_session):
    headers = admin_session["headers"]
    item = client.post(
        "/api/catalog",
        headers=headers,
        json={
            "kind": "service",
            "name": "测试搓澡",
            "price": "30.00",
        },
    ).get_json()["data"]
    band = client.get("/api/wristbands", headers=headers).get_json()["data"][0]
    visit = client.post(f"/api/wristbands/{band['id']}/open", headers=headers, json={}).get_json()["data"]
    created = client.post(
        f"/api/visits/{visit['id']}/items",
        headers=headers,
        json={
            "catalog_item_id": item["id"],
            "quantity": 1,
            "unit_price": "0.01",
            "total_amount": "0.01",
        },
    )
    assert created.status_code == 201
    assert created.get_json()["data"]["total_amount"] == "30.00"


def test_mobile_admin_refresh_session_is_limited_to_eight_hours(client, admin_session, app):
    from flask_jwt_extended import decode_token

    client.post("/api/terminals/register", json={"code": "MOBILE-ADMIN-TEST", "name": "测试手机"})
    login = client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "admin123",
            "terminal_code": "MOBILE-ADMIN-TEST",
        },
    ).get_json()["data"]
    with app.app_context():
        claims = decode_token(login["refresh_token"])
    assert claims["exp"] - claims["iat"] == 8 * 3600
    assert claims["session_expires_at"] == claims["exp"]


def test_refresh_cannot_extend_the_absolute_session_deadline(client, admin_session, app):
    from datetime import datetime, timedelta, timezone

    from flask_jwt_extended import create_refresh_token, decode_token

    with app.app_context():
        claims = decode_token(admin_session["login"]["refresh_token"])
        deadline = int(datetime.now(timezone.utc).timestamp()) + 60
        additional = {key: claims[key] for key in ("role", "terminal_id", "session_id", "session_version")}
        additional["session_expires_at"] = deadline
        refresh_token = create_refresh_token(
            identity=claims["sub"], additional_claims=additional, expires_delta=timedelta(hours=1)
        )
    response = client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})
    assert response.status_code == 200
    with app.app_context():
        access = decode_token(response.get_json()["data"]["access_token"])
    assert access["exp"] <= deadline
    assert access["session_expires_at"] == deadline


def test_valid_jwt_is_rejected_after_absolute_session_expiry(client, admin_session, app):
    from datetime import datetime, timedelta, timezone

    from flask_jwt_extended import create_access_token, create_refresh_token, decode_token

    with app.app_context():
        claims = decode_token(admin_session["login"]["refresh_token"])
        additional = {key: claims[key] for key in ("role", "terminal_id", "session_id", "session_version")}
        additional["session_expires_at"] = int(datetime.now(timezone.utc).timestamp()) - 1
        access = create_access_token(
            identity=claims["sub"], additional_claims=additional, expires_delta=timedelta(hours=1)
        )
        refresh = create_refresh_token(
            identity=claims["sub"], additional_claims=additional, expires_delta=timedelta(hours=1)
        )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 401
    assert client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401


@pytest.mark.parametrize("count", [True, 2.9, 0, "NaN", 2147483648])
def test_pass_count_rejects_boolean_fractional_or_out_of_range_values(client, admin_session, count):
    headers = admin_session["headers"]
    member = client.post("/api/members", headers=headers, json={"phone": "13912345678"}).get_json()["data"]
    response = client.post(
        f"/api/members/{member['id']}/passes",
        headers={**headers, "Idempotency-Key": "invalid-pass-count"},
        json={"count": count, "amount": "40.00", "payment_method": "cash"},
    )
    assert response.status_code == 400
    assert client.get(f"/api/members/{member['id']}", headers=headers).get_json()["data"]["passes"] == []


def test_pass_invalid_expiry_date_is_a_validation_error(client, admin_session):
    headers = admin_session["headers"]
    member = client.post("/api/members", headers=headers, json={"phone": "13912345678"}).get_json()["data"]
    response = client.post(
        f"/api/members/{member['id']}/passes",
        headers={**headers, "Idempotency-Key": "invalid-pass-date"},
        json={"count": 2, "amount": "40.00", "payment_method": "cash", "valid_until": "2026-99-99"},
    )
    assert response.status_code == 400
