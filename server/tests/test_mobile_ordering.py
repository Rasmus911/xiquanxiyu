from decimal import Decimal

from app.extensions import db
from app.models import CatalogItem, OrderItem


def _create_and_login(client, admin_headers, username, role):
    created = client.post(
        "/api/employees",
        json={
            "username": username,
            "display_name": username,
            "password": "staff123",
            "role": role,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": "staff123", "terminal_code": "TEST-01"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.get_json()['data']['access_token']}"}


def _open_seed_band(client, admin_headers, number):
    bands = client.get("/api/wristbands", headers=admin_headers).get_json()["data"]
    band = next(row for row in bands if row["number"] == number)
    response = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=admin_headers)
    assert response.status_code == 201
    return response.get_json()["data"]


def test_scrubber_only_sees_activated_area_and_scrub_catalog(app, client, admin_session):
    admin_headers = admin_session["headers"]
    male_visit = _open_seed_band(client, admin_headers, "8001")
    female_visit = _open_seed_band(client, admin_headers, "9001")
    headers = _create_and_login(client, admin_headers, "male-worker", "male_scrubber")

    response = client.get("/api/mobile/bootstrap", headers=headers)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert [row["number"] for row in data["wristbands"]] == ["8001"]
    assert {row["mobile_scope"] for row in data["catalog"]} <= {"scrub", "both"}
    assert any(row["name"] == "传统搓澡" for row in data["catalog"])
    assert all(row["name"] != "矿泉水" for row in data["catalog"])

    catalog = client.get("/api/catalog", headers=admin_headers).get_json()["data"]
    rest_item = next(row for row in catalog if row["name"] == "矿泉水")
    forbidden_catalog = client.post(
        f"/api/mobile/visits/{male_visit['id']}/items",
        json={"items": [{"catalog_item_id": rest_item["id"], "quantity": 1}]},
        headers={**headers, "Idempotency-Key": "forbidden-catalog"},
    )
    assert forbidden_catalog.status_code == 403
    assert forbidden_catalog.get_json()["error"]["code"] == "PERMISSION_DENIED"

    scrub_item = next(row for row in catalog if row["name"] == "传统搓澡")
    forbidden_area = client.post(
        f"/api/mobile/visits/{female_visit['id']}/items",
        json={"items": [{"catalog_item_id": scrub_item["id"], "quantity": 1}]},
        headers={**headers, "Idempotency-Key": "forbidden-area"},
    )
    assert forbidden_area.status_code == 403
    assert forbidden_area.get_json()["error"]["code"] == "PERMISSION_DENIED"

    desktop_api = client.get("/api/wristbands", headers=headers)
    assert desktop_api.status_code == 200
    assert [row['number'] for row in desktop_api.get_json()['data']] == ['8001']


def test_mobile_valid_order_updates_shared_bill_and_stock(app, client, admin_session):
    admin_headers = admin_session["headers"]
    male_visit = _open_seed_band(client, admin_headers, "8002")
    headers = _create_and_login(client, admin_headers, "scrubber-2", "male_scrubber")
    bootstrap = client.get("/api/mobile/bootstrap", headers=headers).get_json()["data"]
    towel = next(row for row in bootstrap["catalog"] if row["name"] == "一次性搓澡巾")

    response = client.post(
        f"/api/mobile/visits/{male_visit['id']}/items",
        json={"items": [{"catalog_item_id": towel["id"], "quantity": 3}]},
        headers={**headers, "Idempotency-Key": "valid-mobile-order"},
    )
    assert response.status_code == 201
    assert response.get_json()["data"][0]["total_amount"] == "15.00"

    shared_bill = client.get(f"/api/visits/{male_visit['id']}", headers=admin_headers).get_json()["data"]
    assert shared_bill["total_amount"] == "15.00"
    with app.app_context():
        product = db.session.get(CatalogItem, towel["id"])
        order = OrderItem.query.filter_by(visit_id=male_visit["id"], catalog_item_id=towel["id"]).first()
        assert Decimal(product.stock_quantity) == Decimal("7")
        assert Decimal(order.quantity) == Decimal("3")


def test_floor_attendant_sees_both_areas_but_only_rest_catalog(client, admin_session):
    admin_headers = admin_session["headers"]
    _open_seed_band(client, admin_headers, "8003")
    female_visit = _open_seed_band(client, admin_headers, "9003")
    headers = _create_and_login(client, admin_headers, "floor-worker", "floor_attendant")
    data = client.get("/api/mobile/bootstrap", headers=headers).get_json()["data"]

    assert {row["number"] for row in data["wristbands"]} == {"8003", "9003"}
    assert {row["mobile_scope"] for row in data["catalog"]} <= {"rest", "both"}
    assert any(row["name"] == "矿泉水" for row in data["catalog"])
    assert all(row["name"] != "传统搓澡" for row in data["catalog"])

    water = next(row for row in data["catalog"] if row["name"] == "矿泉水")
    response = client.post(
        f"/api/mobile/visits/{female_visit['id']}/items",
        json={"items": [{"catalog_item_id": water["id"], "quantity": 2}]},
        headers={**headers, "Idempotency-Key": "floor-mobile-order"},
    )
    assert response.status_code == 201


def test_admin_sees_both_areas_and_all_active_sales_catalog(client, admin_session):
    admin_headers = admin_session["headers"]
    male_visit = _open_seed_band(client, admin_headers, "8006")
    _open_seed_band(client, admin_headers, "9006")
    frontdesk_item = client.post(
        "/api/catalog",
        json={
            "kind": "service",
            "category": "前台项目",
            "name": "管理员手机可售项目",
            "mobile_scope": "frontdesk",
            "price": "12.00",
        },
        headers=admin_headers,
    )
    assert frontdesk_item.status_code == 201

    response = client.get("/api/mobile/bootstrap", headers=admin_headers)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["employee"]["role"] == "admin"
    assert data["employee"]["role_label"] == "系统管理员"
    assert {row["number"] for row in data["wristbands"]} == {"8006", "9006"}
    assert {row["mobile_scope"] for row in data["catalog"]} == {"frontdesk", "scrub", "rest"}

    mobile_item = next(row for row in data["catalog"] if row["name"] == "管理员手机可售项目")
    order = client.post(
        f"/api/mobile/visits/{male_visit['id']}/items",
        json={"items": [{"catalog_item_id": mobile_item["id"], "quantity": 1}]},
        headers={**admin_headers, "Idempotency-Key": "admin-mobile-order"},
    )
    assert order.status_code == 201


def test_mobile_order_requires_idempotency_key(client, admin_session):
    admin_headers = admin_session["headers"]
    visit = _open_seed_band(client, admin_headers, "8004")
    headers = _create_and_login(client, admin_headers, "missing-key-worker", "male_scrubber")
    bootstrap = client.get("/api/mobile/bootstrap", headers=headers).get_json()["data"]
    towel = next(row for row in bootstrap["catalog"] if row["name"] == "一次性搓澡巾")

    response = client.post(
        f"/api/mobile/visits/{visit['id']}/items",
        json={"items": [{"catalog_item_id": towel["id"], "quantity": 1}]},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "IDEMPOTENCY_REQUIRED"


def test_mobile_order_idempotency_does_not_double_charge_or_decrement_stock(app, client, admin_session):
    admin_headers = admin_session["headers"]
    visit = _open_seed_band(client, admin_headers, "8005")
    headers = _create_and_login(client, admin_headers, "idempotent-worker", "male_scrubber")
    bootstrap = client.get("/api/mobile/bootstrap", headers=headers).get_json()["data"]
    towel = next(row for row in bootstrap["catalog"] if row["name"] == "一次性搓澡巾")
    request_headers = {**headers, "Idempotency-Key": "mobile-order-8005-1"}
    body = {"items": [{"catalog_item_id": towel["id"], "quantity": 2}]}

    first = client.post(f"/api/mobile/visits/{visit['id']}/items", json=body, headers=request_headers)
    repeated = client.post(f"/api/mobile/visits/{visit['id']}/items", json=body, headers=request_headers)

    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.get_json()["data"] == first.get_json()["data"]
    with app.app_context():
        orders = OrderItem.query.filter_by(visit_id=visit["id"], catalog_item_id=towel["id"]).all()
        product = db.session.get(CatalogItem, towel["id"])
        assert len(orders) == 1
        assert Decimal(product.stock_quantity) == Decimal("8")
