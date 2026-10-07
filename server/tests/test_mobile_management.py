from decimal import Decimal

from app.extensions import db
from app.models import CatalogItem, Employee, InventoryMovement


def _create_and_login(client, admin_headers, username, role="admin", display_name=None):
    created = client.post(
        "/api/employees",
        json={
            "username": username,
            "display_name": display_name or username,
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


def _grant_mobile_full_access(app, username):
    with app.app_context():
        employee = Employee.query.filter_by(username=username).one()
        employee.mobile_full_access = True
        db.session.commit()


def test_named_mobile_owner_gets_management_capabilities_and_full_catalog(client, admin_session, app):
    admin_headers = admin_session["headers"]
    owner_headers = _create_and_login(client, admin_headers, "于在跃")
    _grant_mobile_full_access(app, "于在跃")
    client.post(
        "/api/catalog",
        json={
            "kind": "service",
            "category": "前台项目",
            "name": "手机负责人专享可售项目",
            "mobile_scope": "frontdesk",
            "price": "18.00",
        },
        headers=admin_headers,
    )

    response = client.get("/api/mobile/bootstrap", headers=owner_headers)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["employee"]["capabilities"] == {
        'orders_view': True,
        "order_all": True,
        "catalog_all": True,
        "reports_view": True,
        "inventory_manage": True,
        "reports": True,
        "inventory_add": True,
    }
    assert any(row["name"] == "手机负责人专享可售项目" for row in data["catalog"])


def test_named_mobile_owner_display_name_gets_management_capabilities(client, admin_session, app):
    owner_headers = _create_and_login(
        client,
        admin_session["headers"],
        "owner-yzy",
        display_name="于在跃",
    )
    _grant_mobile_full_access(app, "owner-yzy")

    response = client.get("/api/mobile/bootstrap", headers=owner_headers)

    assert response.status_code == 200
    assert response.get_json()["data"]["employee"]["capabilities"] == {
        'orders_view': True,
        "order_all": True,
        "catalog_all": True,
        "reports_view": True,
        "inventory_manage": True,
        "reports": True,
        "inventory_add": True,
    }


def test_named_mobile_owner_can_order_any_active_service(client, admin_session, app):
    admin_headers = admin_session["headers"]
    owner_headers = _create_and_login(client, admin_headers, "于景辉")
    _grant_mobile_full_access(app, "于景辉")
    with app.app_context():
        legacy = CatalogItem(
            kind="service",
            category="历史项目",
            name="旧版未分类服务",
            mobile_scope="legacy",
            price=Decimal("26.00"),
        )
        db.session.add(legacy)
        db.session.commit()
        legacy_id = legacy.id

    wristbands = client.get("/api/wristbands", headers=admin_headers).get_json()["data"]
    wristband = next(row for row in wristbands if row["number"] == "8001")
    opened = client.post(
        f"/api/wristbands/{wristband['id']}/open",
        json={},
        headers=admin_headers,
    )
    assert opened.status_code == 201
    visit_id = opened.get_json()["data"]["id"]

    bootstrap = client.get("/api/mobile/bootstrap", headers=owner_headers)
    ordered = client.post(
        f"/api/mobile/visits/{visit_id}/items",
        json={"items": [{"catalog_item_id": legacy_id, "quantity": 1}]},
        headers={**owner_headers, "Idempotency-Key": "owner-legacy-service-1"},
    )

    assert any(row["id"] == legacy_id for row in bootstrap.get_json()["data"]["catalog"])
    assert ordered.status_code == 201


def test_new_admin_cannot_gain_mobile_management_by_reusing_owner_name(client, admin_session):
    copied_name_headers = _create_and_login(
        client,
        admin_session["headers"],
        "new-admin-copy",
        display_name="于在跃",
    )

    bootstrap = client.get("/api/mobile/bootstrap", headers=copied_name_headers)
    report = client.get("/api/mobile/management/report", headers=copied_name_headers)

    assert bootstrap.get_json()["data"]["employee"]["capabilities"] == {
        'orders_view': True,
        "order_all": False,
        "catalog_all": False,
        "reports_view": False,
        "inventory_manage": False,
        "reports": False,
        "inventory_add": False,
    }
    assert report.status_code == 403


def test_other_admin_cannot_use_mobile_management_endpoints(client, admin_session):
    admin_headers = admin_session["headers"]
    other_headers = _create_and_login(client, admin_headers, "新增管理员")

    bootstrap = client.get("/api/mobile/bootstrap", headers=other_headers)
    report = client.get("/api/mobile/management/report", headers=other_headers)
    inventory = client.get("/api/mobile/management/inventory", headers=other_headers)

    assert bootstrap.status_code == 200
    assert bootstrap.get_json()["data"]["employee"]["capabilities"] == {
        'orders_view': True,
        "order_all": False,
        "catalog_all": False,
        "reports_view": False,
        "inventory_manage": False,
        "reports": False,
        "inventory_add": False,
    }
    assert report.status_code == 403
    assert report.get_json()["error"]["code"] == "PERMISSION_DENIED"
    assert inventory.status_code == 403
    assert inventory.get_json()["error"]["code"] == "PERMISSION_DENIED"


def test_mobile_management_report_matches_desktop_report(client, admin_session, app):
    admin_headers = admin_session["headers"]
    owner_headers = _create_and_login(client, admin_headers, "李丽娜")
    _grant_mobile_full_access(app, "李丽娜")
    query = "start=2026-09-20T00:00:00&end=2026-09-21T00:00:00"

    mobile = client.get(f"/api/mobile/management/report?{query}", headers=owner_headers)
    summary = client.get(f"/api/reports/summary?{query}", headers=admin_headers)
    items = client.get(f"/api/reports/items?{query}", headers=admin_headers)
    trend = client.get(f"/api/reports/trend?{query}", headers=admin_headers)
    insights = client.get(f"/api/reports/insights?{query}", headers=admin_headers)

    assert mobile.status_code == 200
    assert mobile.get_json()["data"] == {
        "summary": summary.get_json()["data"],
        "items": items.get_json()["data"],
        "trend": trend.get_json()["data"],
        "insights": insights.get_json()["data"],
    }


def test_mobile_inventory_add_is_idempotent(client, admin_session, app):
    admin_headers = admin_session["headers"]
    owner_headers = _create_and_login(client, admin_headers, "于景辉")
    _grant_mobile_full_access(app, "于景辉")
    inventory = client.get("/api/mobile/management/inventory", headers=owner_headers)
    assert inventory.status_code == 200
    product = next(row for row in inventory.get_json()["data"] if row["name"] == "矿泉水")
    request_headers = {**owner_headers, "Idempotency-Key": "mobile-purchase-water-1"}
    body = {"catalog_item_id": product["id"], "quantity": "3", "note": "手机采购入库"}

    first = client.post("/api/mobile/management/inventory/add", json=body, headers=request_headers)
    repeated = client.post("/api/mobile/management/inventory/add", json=body, headers=request_headers)

    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.get_json()["data"] == first.get_json()["data"]
    with app.app_context():
        stored = db.session.get(CatalogItem, product["id"])
        movements = InventoryMovement.query.filter_by(idempotency_key="mobile-purchase-water-1").all()
        assert Decimal(stored.stock_quantity) == Decimal("13")
        assert len(movements) == 1
