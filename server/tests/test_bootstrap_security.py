from app import create_app
from app.config import TestConfig
from app.extensions import db


class BootstrapProtectedTestConfig(TestConfig):
    BOOTSTRAP_TOKEN = "setup-secret"


def test_bootstrap_requires_configured_token():
    app = create_app(BootstrapProtectedTestConfig)
    client = app.test_client()
    payload = {"username": "admin", "display_name": "管理员", "password": "admin123"}

    with app.app_context():
        db.create_all()

        missing = client.post("/api/auth/bootstrap", json=payload)
        assert missing.status_code == 403
        assert missing.get_json()["error"]["code"] == "INVALID_BOOTSTRAP_TOKEN"

        wrong = client.post("/api/auth/bootstrap", json={**payload, "bootstrap_token": "wrong"})
        assert wrong.status_code == 403

        created = client.post(
            "/api/auth/bootstrap",
            json={**payload, "bootstrap_token": "setup-secret"},
        )
        assert created.status_code == 201

        repeated = client.post(
            "/api/auth/bootstrap",
            json={**payload, "bootstrap_token": "setup-secret"},
        )
        assert repeated.status_code == 409

        db.session.remove()
        db.drop_all()
