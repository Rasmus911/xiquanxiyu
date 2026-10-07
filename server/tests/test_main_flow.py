from datetime import datetime, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import CatalogItem, InventoryMovement, OrderItem, Settlement, SettlementVisit, Visit, Wristband


def test_open_order_checkout_and_inventory(app, client, admin_session):
    headers = admin_session["headers"]
    created = client.post(
        "/api/wristbands/bulk",
        json={"start": 1, "end": 2, "width": 3},
        headers=headers,
    )
    assert created.status_code == 201
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    band = next(row for row in bands if row["number"] == "001")

    product_response = client.post(
        "/api/catalog",
        json={
            "kind": "product",
            "category": "饮料",
            "name": "矿泉水",
            "price": 3.5,
            "stock_tracked": True,
        },
        headers=headers,
    )
    assert product_response.status_code == 201
    product = product_response.get_json()["data"]
    stock = client.post(
        "/api/inventory/adjust",
        json={
            "catalog_item_id": product["id"],
            "movement_type": "opening",
            "quantity": 10,
            "note": "测试期初",
            "idempotency_key": "stock-1",
        },
        headers={**headers, "Idempotency-Key": "stock-1"},
    )
    assert stock.status_code == 200

    opened = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers)
    assert opened.status_code == 201
    visit = opened.get_json()["data"]
    item = client.post(
        f"/api/visits/{visit['id']}/items",
        json={"catalog_item_id": product["id"], "quantity": 2},
        headers=headers,
    )
    assert item.status_code == 201
    assert item.get_json()["data"]["total_amount"] == "7.00"

    repriced = client.patch(
        f"/api/catalog/{product['id']}",
        json={"price": 4},
        headers=headers,
    )
    assert repriced.status_code == 200
    refreshed_visit = client.get(f"/api/visits/{visit['id']}", headers=headers).get_json()["data"]
    assert refreshed_visit["total_amount"] == "8.00"

    checkout = client.post(
        "/api/checkout",
        json={
            "visit_ids": [visit["id"]],
            "payments": [{"method": "cash", "amount": 8}],
            "idempotency_key": "checkout-1",
        },
        headers={**headers, "Idempotency-Key": "checkout-1"},
    )
    assert checkout.status_code == 201
    settlement = checkout.get_json()["data"]
    assert settlement["total_amount"] == "8.00"

    repeated = client.post(
        "/api/checkout",
        json={
            "visit_ids": [visit["id"]],
            "payments": [{"method": "cash", "amount": 8}],
            "idempotency_key": "checkout-1",
        },
        headers={**headers, "Idempotency-Key": "checkout-1"},
    )
    assert repeated.status_code == 200
    assert repeated.get_json()["data"]["id"] == settlement["id"]

    start = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    trend = client.get("/api/reports/trend", query_string={"start": start, "end": end}, headers=headers)
    assert trend.status_code == 200
    trend_rows = trend.get_json()["data"]
    assert sum(Decimal(row["revenue"]) for row in trend_rows) == Decimal("8.00")
    assert sum(row["settlement_count"] for row in trend_rows) == 1

    item_report = client.get("/api/reports/items", query_string={"start": start, "end": end}, headers=headers)
    assert item_report.status_code == 200
    item_rows = item_report.get_json()["data"]
    assert any(row["name"] == "矿泉水" and row["amount"] == "8.00" for row in item_rows)

    client.patch(f"/api/catalog/{product['id']}", json={"price": 5}, headers=headers)

    with app.app_context():
        stored_product = db.session.get(CatalogItem, product["id"])
        stored_band = db.session.get(Wristband, band["id"])
        stored_item = OrderItem.query.filter_by(visit_id=visit["id"], catalog_item_id=product["id"]).first()
        assert Decimal(stored_product.stock_quantity) == Decimal("8")
        assert Decimal(stored_item.unit_price) == Decimal("4")
        assert Decimal(stored_item.total_amount) == Decimal("8")
        assert stored_band.status == "available"
        assert Settlement.query.count() == 1
        assert InventoryMovement.query.count() == 2


def test_lost_and_replace(client, admin_session):
    headers = admin_session["headers"]
    client.post("/api/wristbands/bulk", json={"start": 10, "end": 11, "width": 3}, headers=headers)
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    source = next(row for row in bands if row["number"] == "010")
    opened = client.post(f"/api/wristbands/{source['id']}/open", json={}, headers=headers).get_json()["data"]
    lost = client.post(f"/api/wristbands/{source['id']}/lost", json={"reason": "顾客遗失"}, headers=headers)
    assert lost.status_code == 200
    assert lost.get_json()["data"]["fee"] == "20.00"
    replaced = client.post(
        f"/api/wristbands/{source['id']}/replace",
        json={"target_number": "011"},
        headers=headers,
    )
    assert replaced.status_code == 200
    visit = client.get(f"/api/visits/{opened['id']}", headers=headers).get_json()["data"]
    assert visit["wristband_number"] == "011"
    assert visit["total_amount"] == "20.00"


def test_lost_recover_and_unsettled_fee_refresh(client, admin_session):
    headers = admin_session["headers"]
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    band = next(row for row in bands if row["number"] == "8001")
    visit = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers).get_json()["data"]

    lost = client.post(f"/api/wristbands/{band['id']}/lost", json={"reason": "暂时找不到"}, headers=headers)
    assert lost.status_code == 200
    changed_fee = client.put("/api/settings/lost_wristband_fee", json={"value": 35}, headers=headers)
    assert changed_fee.status_code == 200
    refreshed = client.get(f"/api/visits/{visit['id']}", headers=headers).get_json()["data"]
    assert refreshed["total_amount"] == "35.00"

    recovered = client.post(f"/api/wristbands/{band['id']}/recover", json={}, headers=headers)
    assert recovered.status_code == 200
    assert recovered.get_json()["data"]["removed_compensation"] == "35.00"
    refreshed = client.get(f"/api/visits/{visit['id']}", headers=headers).get_json()["data"]
    assert refreshed["total_amount"] == "0.00"
    assert next(item for item in refreshed["items"] if item["kind"] == "compensation")["status"] == "voided"
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    assert next(row for row in bands if row["number"] == "8001")["status"] == "in_use"


def test_cross_area_linked_checkout(client, admin_session):
    headers = admin_session["headers"]
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    male = next(row for row in bands if row["number"] == "8001")
    female = next(row for row in bands if row["number"] == "9001")
    male_visit = client.post(f"/api/wristbands/{male['id']}/open", json={}, headers=headers).get_json()["data"]

    linked = client.post(
        "/api/wristbands/link-batch",
        json={"wristband_ids": [male["id"], female["id"]]},
        headers=headers,
    )
    assert linked.status_code == 200
    assert linked.get_json()["data"]["linked_wristbands"] == ["8001", "9001"]
    assert linked.get_json()["data"]["auto_opened"] == ["9001"]

    detail = client.get(f"/api/visits/{male_visit['id']}", headers=headers).get_json()["data"]
    assert {row["wristband_number"] for row in detail["linked_visits"]} == {"8001", "9001"}
    female_visit = next(row for row in detail["linked_visits"] if row["wristband_number"] == "9001")

    services = client.get("/api/catalog", headers=headers).get_json()["data"]
    milk = next(row for row in services if row["name"] == "牛奶浴")
    client.post(
        f"/api/visits/{female_visit['id']}/items",
        json={"catalog_item_id": milk["id"], "quantity": 1},
        headers=headers,
    )

    preview = client.post("/api/checkout/preview", json={"visit_ids": [male_visit["id"]]}, headers=headers)
    preview_data = preview.get_json()["data"]
    assert len(preview_data["visits"]) == 2
    assert preview_data["auto_included_linked_visits"] == 1
    assert preview_data["total_amount"] == "38.00"

    checkout = client.post(
        "/api/checkout",
        json={
            "visit_ids": [male_visit["id"]],
            "payments": [{"method": "cash", "amount": 38}],
            "idempotency_key": "linked-checkout",
        },
        headers={**headers, "Idempotency-Key": "linked-checkout"},
    )
    assert checkout.status_code == 201
    assert len(checkout.get_json()["data"]["visits"]) == 2
    refreshed = client.get("/api/wristbands", headers=headers).get_json()["data"]
    assert next(row for row in refreshed if row["number"] == "8001")["status"] == "available"
    assert next(row for row in refreshed if row["number"] == "9001")["status"] == "available"


def test_linked_wristband_can_checkout_individually(client, admin_session):
    headers = admin_session["headers"]
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    male = next(row for row in bands if row["number"] == "8001")
    female = next(row for row in bands if row["number"] == "9001")
    male_visit = client.post(f"/api/wristbands/{male['id']}/open", json={}, headers=headers).get_json()["data"]
    linked = client.post(
        "/api/wristbands/link-batch",
        json={"wristband_ids": [male["id"], female["id"]]},
        headers=headers,
    )
    assert linked.status_code == 200

    detail = client.get(f"/api/visits/{male_visit['id']}", headers=headers).get_json()["data"]
    female_visit = next(row for row in detail["linked_visits"] if row["wristband_number"] == "9001")
    services = client.get("/api/catalog", headers=headers).get_json()["data"]
    milk = next(row for row in services if row["name"] == "牛奶浴")
    added = client.post(
        f"/api/visits/{male_visit['id']}/items/batch",
        json={"items": [{"catalog_item_id": milk["id"], "quantity": 1}]},
        headers={**headers, "Idempotency-Key": "linked-individual-add"},
    )
    assert added.status_code == 201

    assert len(added.get_json()["data"]) == 1

    preview = client.post(
        "/api/checkout/preview",
        json={"visit_ids": [male_visit["id"]], "checkout_scope": "selected"},
        headers=headers,
    )
    assert preview.status_code == 200
    preview_data = preview.get_json()["data"]
    assert [row["visit_id"] for row in preview_data["visits"]] == [male_visit["id"]]
    assert preview_data["auto_included_linked_visits"] == 0

    checkout = client.post(
        "/api/checkout",
        json={
            "visit_ids": [male_visit["id"]],
            "checkout_scope": "selected",
            "payments": [{"method": "cash", "amount": preview_data["total_amount"]}],
            "idempotency_key": "individual-linked-checkout",
        },
        headers={**headers, "Idempotency-Key": "individual-linked-checkout"},
    )
    assert checkout.status_code == 201
    assert len(checkout.get_json()["data"]["visits"]) == 1

    refreshed = client.get("/api/wristbands", headers=headers).get_json()["data"]
    assert next(row for row in refreshed if row["number"] == "8001")["status"] == "available"
    assert next(row for row in refreshed if row["number"] == "9001")["status"] == "in_use"
    remaining = client.get(f"/api/visits/{female_visit['id']}", headers=headers).get_json()["data"]
    assert remaining["party_id"] is None
    assert [row["wristband_number"] for row in remaining["linked_visits"]] == ["9001"]


def test_three_person_party_can_settle_any_one_and_keep_remaining_linked(app, client, admin_session):
    headers = admin_session["headers"]
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    selected_bands = [next(row for row in bands if row["number"] == number) for number in ("8001", "8002", "9001")]
    first_visit = client.post(f"/api/wristbands/{selected_bands[0]['id']}/open", json={}, headers=headers).get_json()[
        "data"
    ]
    linked = client.post(
        "/api/wristbands/link-batch",
        json={"wristband_ids": [row["id"] for row in selected_bands]},
        headers=headers,
    )
    assert linked.status_code == 200
    detail = client.get(f"/api/visits/{first_visit['id']}", headers=headers).get_json()["data"]
    visits_by_band = {row["wristband_number"]: row for row in detail["linked_visits"]}
    original_party_id = visits_by_band["8001"]["party_id"]
    assert original_party_id
    services = [
        row for row in client.get("/api/catalog", headers=headers).get_json()["data"] if row["kind"] == "service"
    ][:3]
    for visit_row, service in zip(visits_by_band.values(), services, strict=True):
        added = client.post(
            f"/api/visits/{visit_row['id']}/items",
            json={"catalog_item_id": service["id"], "quantity": 1},
            headers=headers,
        )
        assert added.status_code == 201

    preview = client.post(
        "/api/checkout/preview",
        json={"visit_ids": [visits_by_band["8001"]["id"]], "checkout_scope": "selected"},
        headers=headers,
    ).get_json()["data"]
    checkout_payload = {
        "visit_ids": [visits_by_band["8001"]["id"]],
        "checkout_scope": "selected",
        "payments": [{"method": "cash", "amount": preview["total_amount"]}],
        "idempotency_key": "three-person-first-only",
    }
    checkout_headers = {**headers, "Idempotency-Key": "three-person-first-only"}
    first = client.post("/api/checkout", json=checkout_payload, headers=checkout_headers)
    repeated = client.post("/api/checkout", json=checkout_payload, headers=checkout_headers)

    assert first.status_code == 201, first.get_json()
    assert repeated.status_code == 200
    refreshed = client.get("/api/wristbands", headers=headers).get_json()["data"]
    assert next(row for row in refreshed if row["number"] == "8001")["status"] == "available"
    assert next(row for row in refreshed if row["number"] == "8002")["status"] == "in_use"
    assert next(row for row in refreshed if row["number"] == "9001")["status"] == "in_use"
    with app.app_context():
        closed = db.session.get(Visit, visits_by_band["8001"]["id"])
        second = db.session.get(Visit, visits_by_band["8002"]["id"])
        third = db.session.get(Visit, visits_by_band["9001"]["id"])
        assert closed.status == "closed" and closed.party_id is None
        assert second.status == "open" and second.party_id == original_party_id
        assert third.status == "open" and third.party_id == original_party_id
        assert Settlement.query.filter_by(idempotency_key="three-person-first-only").count() == 1
        settlement = Settlement.query.filter_by(idempotency_key="three-person-first-only").one()
        assert SettlementVisit.query.filter_by(settlement_id=settlement.id).count() == 1


def test_void_item_does_not_require_reason(client, admin_session):
    headers = admin_session["headers"]
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    band = next(row for row in bands if row["number"] == "8001")
    visit = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers).get_json()["data"]
    catalog = client.get("/api/catalog", headers=headers).get_json()["data"]
    milk = next(row for row in catalog if row["name"] == "牛奶浴")
    item = client.post(
        f"/api/visits/{visit['id']}/items",
        json={"catalog_item_id": milk["id"], "quantity": 1},
        headers=headers,
    ).get_json()["data"]

    voided = client.post(
        f"/api/visits/{visit['id']}/items/{item['id']}/void",
        json={},
        headers={**headers, "Idempotency-Key": "void-without-reason"},
    )
    assert voided.status_code == 200
    assert voided.get_json()["data"]["status"] == "voided"
    assert voided.get_json()["data"]["void_reason"] == "前台直接撤销"


def test_desktop_batch_order_is_idempotent(app, client, admin_session):
    headers = admin_session["headers"]
    band = next(
        row for row in client.get("/api/wristbands", headers=headers).get_json()["data"] if row["number"] == "8003"
    )
    visit = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers).get_json()["data"]
    product = client.post(
        "/api/catalog",
        json={
            "kind": "product",
            "category": "测试",
            "name": "幂等测试饮料",
            "price": 5,
            "stock_tracked": True,
        },
        headers=headers,
    ).get_json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={
            "catalog_item_id": product["id"],
            "movement_type": "opening",
            "quantity": 10,
            "note": "幂等测试",
            "idempotency_key": "desktop-batch-stock",
        },
        headers={**headers, "Idempotency-Key": "desktop-batch-stock"},
    )
    request_headers = {**headers, "Idempotency-Key": "desktop-batch-same-key"}
    payload = {"items": [{"catalog_item_id": product["id"], "quantity": 2}]}

    first = client.post(f"/api/visits/{visit['id']}/items/batch", json=payload, headers=request_headers)
    repeated = client.post(f"/api/visits/{visit['id']}/items/batch", json=payload, headers=request_headers)

    assert first.status_code == 201
    assert repeated.status_code in {200, 201}
    assert "原加单结果" in repeated.get_json()["message"]
    with app.app_context():
        active = OrderItem.query.filter_by(visit_id=visit["id"], catalog_item_id=product["id"], status="active").all()
        assert len(active) == 1
        assert db.session.get(CatalogItem, product["id"]).stock_quantity == Decimal("8.000")


def test_desktop_void_is_idempotent(app, client, admin_session):
    headers = admin_session["headers"]
    band = next(
        row for row in client.get("/api/wristbands", headers=headers).get_json()["data"] if row["number"] == "8004"
    )
    visit = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers).get_json()["data"]
    product = client.post(
        "/api/catalog",
        json={
            "kind": "product",
            "category": "测试",
            "name": "幂等撤销饮料",
            "price": 5,
            "stock_tracked": True,
        },
        headers=headers,
    ).get_json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={
            "catalog_item_id": product["id"],
            "movement_type": "opening",
            "quantity": 10,
            "note": "幂等撤销测试",
            "idempotency_key": "desktop-void-stock",
        },
        headers={**headers, "Idempotency-Key": "desktop-void-stock"},
    )
    item = client.post(
        f"/api/visits/{visit['id']}/items",
        json={"catalog_item_id": product["id"], "quantity": 2},
        headers=headers,
    ).get_json()["data"]
    request_headers = {**headers, "Idempotency-Key": "desktop-void-same-key"}

    first = client.post(
        f"/api/visits/{visit['id']}/items/{item['id']}/void",
        json={},
        headers=request_headers,
    )
    repeated = client.post(
        f"/api/visits/{visit['id']}/items/{item['id']}/void",
        json={},
        headers=request_headers,
    )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert "原撤销结果" in repeated.get_json()["message"]
    with app.app_context():
        assert db.session.get(CatalogItem, product["id"]).stock_quantity == Decimal("10.000")
        returns = InventoryMovement.query.filter_by(
            reference_type="order_item",
            reference_id=item["id"],
            movement_type="void_return",
        ).all()
        assert len(returns) == 1


def test_password_protected_force_clear_restores_inventory(client, admin_session):
    headers = admin_session["headers"]
    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    band = next(row for row in bands if row["number"] == "8002")
    visit = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers).get_json()["data"]
    catalog = client.get("/api/catalog", headers=headers).get_json()["data"]
    towel = next(row for row in catalog if row["name"] == "一次性搓澡巾")
    client.post(
        "/api/inventory/adjust",
        json={
            "catalog_item_id": towel["id"],
            "movement_type": "opening",
            "quantity": 5,
            "note": "强制清空返库测试",
            "idempotency_key": "force-clear-stock",
        },
        headers={**headers, "Idempotency-Key": "force-clear-stock"},
    )
    added = client.post(
        f"/api/visits/{visit['id']}/items",
        json={"catalog_item_id": towel["id"], "quantity": 1},
        headers=headers,
    )
    assert added.status_code == 201

    denied = client.post(
        f"/api/wristbands/{band['id']}/force-clear",
        json={"password": "12345678"},
        headers=headers,
    )
    assert denied.status_code == 403
    cleared = client.post(
        f"/api/wristbands/{band['id']}/force-clear",
        json={"password": "admin123", "reason": "测试误开单清空"},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.get_json()["data"]["cleared_amount"] == "5.00"

    refreshed = client.get("/api/wristbands", headers=headers).get_json()["data"]
    assert next(row for row in refreshed if row["number"] == "8002")["status"] == "available"
    inventory = client.get("/api/inventory", headers=headers).get_json()["data"]
    assert next(row for row in inventory if row["id"] == towel["id"])["stock_quantity"] == "15.000"


def test_purchase_can_use_default_note_but_sensitive_adjustments_require_reason(client, admin_session):
    headers = admin_session["headers"]
    product = next(
        row for row in client.get("/api/inventory", headers=headers).get_json()["data"] if row["name"] == "矿泉水"
    )
    purchase = client.post(
        "/api/inventory/adjust",
        json={
            "catalog_item_id": product["id"],
            "movement_type": "purchase",
            "quantity": 2,
            "note": "",
        },
        headers={**headers, "Idempotency-Key": "blank-purchase-note"},
    )
    assert purchase.status_code == 200
    assert purchase.get_json()["data"]["note"] == "采购入库"

    for movement_type in ("loss", "adjustment"):
        denied = client.post(
            "/api/inventory/adjust",
            json={
                "catalog_item_id": product["id"],
                "movement_type": movement_type,
                "quantity": 1,
                "note": "",
            },
            headers={**headers, "Idempotency-Key": f"blank-{movement_type}-note"},
        )
        assert denied.status_code == 400
