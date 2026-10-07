from app import create_app
from app.config import TestConfig


def test_android_capacitor_origin_can_call_api(client):
    response = client.options(
        "/api/auth/login",
        headers={
            "Origin": "https://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") == "https://localhost"
    allowed_headers = response.headers.get("Access-Control-Allow-Headers", "").lower()
    assert "content-type" in allowed_headers
    assert "x-request-id" in allowed_headers


def test_android_origin_remains_allowed_with_legacy_production_cors_setting():
    class LegacyProductionConfig(TestConfig):
        CORS_ORIGINS = ["null"]

    app = create_app(LegacyProductionConfig)
    with app.test_client() as client:
        response = client.options(
            "/api/auth/login",
            headers={
                "Origin": "https://localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-request-id",
            },
        )

    assert response.headers.get("Access-Control-Allow-Origin") == "https://localhost"
