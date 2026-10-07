"""Photo count imports exercise HTTP guards and actual immutable stock evidence."""

import base64
import hashlib
from pathlib import Path

import pytest

from app.audit_service import verify_audit_chain
from app.extensions import db
from app.models import AuditLog, BusinessPeriod, BusinessStateModel, StockItem, StockMovement

HEADER = (
    "source_photo,row,name,category,base_unit,package_unit,units_per_package,"
    "package_quantity,basic_quantity,review_status\n"
)
BOXES = HEADER + "photo1,1,奶浴袋,搓澡耗材,袋,箱,200,4,800,ready\n"
ROOT = "/api/inventory/photo-import"


def source(csv=BOXES, mapping=None):
    raw = csv.encode("utf-8") if isinstance(csv, str) else csv
    return {
        "source_base64": base64.b64encode(raw).decode("ascii"),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "mapping": mapping if mapping is not None else {"1": {"create": True}},
    }


def preview(client, h, body):
    response = client.post(ROOT + "/preview", headers=h, json=body)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def confirmation(body, result):
    return {**body, "confirm": True, "preview_digest": result["preview_digest"], "period_id": result["period_id"]}


def apply(client, h, body, key="photo-count"):
    return client.post(ROOT + "/apply", headers={**h, "Idempotency-Key": key}, json=body)


def master(client, h, balance="50"):
    r = client.post(
        "/api/inventory/stock-items",
        headers={**h, "Idempotency-Key": "existing"},
        json={
            "name": "既有主档",
            "category": "搓澡耗材",
            "base_unit": "袋",
            "package_unit": "箱",
            "units_per_package": "200",
            "opening_quantity": balance,
        },
    )
    assert r.status_code == 201
    return r.get_json()["data"]


def test_literal_boxes_preview_nonmutating_apply_targets_800_and_global_replay(client, admin_session):
    h = admin_session["headers"]
    item = master(client, h)
    body = source(mapping={"1": {"stock_item_id": item["id"]}})
    before = (StockItem.query.count(), StockMovement.query.count(), AuditLog.query.count())
    result = preview(client, h, body)
    assert (StockItem.query.count(), StockMovement.query.count(), AuditLog.query.count()) == before
    row = result["rows"][0]
    assert row["target_quantity"] == "800.000"
    assert row["input_quantity"] == "4.000" and row["input_unit"] == "箱" and row["base_unit"] == "袋"
    assert row["before"]["stock_quantity"] == "50.000" and row["delta"] == "750.000"
    request = confirmation(body, result)
    response = apply(client, h, request)
    assert response.status_code == 200, response.get_json()
    receipt = response.get_json()["data"]
    assert receipt["rows"][0]["after"]["stock_quantity"] == "800.000"
    movement = StockMovement.query.filter_by(movement_type="photo_count").one()
    assert str(movement.quantity) == "750.000" and str(movement.input_quantity) == "4.000"
    assert str(movement.conversion_factor) == "200.000"
    assert movement.package_unit_snapshot == "箱" and movement.base_unit_snapshot == "袋"
    assert movement.reference_id == receipt["receipt_id"]
    audit = AuditLog.query.filter_by(action="stock.photo_import").one()
    assert audit.entity_id == body["source_sha256"] and audit.employee_id and audit.terminal_id and audit.request_id
    assert audit.details["preview"]["rows"][0]["evidence"]["package_quantity"] == "4"
    for key in ("photo-count", "fresh-request-key"):
        again = apply(client, h, request, key)
        assert again.status_code == 200 and again.get_json()["data"] == receipt
    assert StockMovement.query.count() == before[1] + 1
    assert AuditLog.query.filter_by(action="stock.photo_import").count() == 1
    assert verify_audit_chain() == (True, None)


def test_create_explicit_zero_delta_receipt_and_preserve_unmentioned(client, admin_session):
    h = admin_session["headers"]
    unrelated = master(client, h)
    body = source(BOXES.replace(",4,800,", ",0,0,"))
    r = apply(client, h, confirmation(body, preview(client, h, body)))
    assert r.status_code == 200, r.get_json()
    created = r.get_json()["data"]["rows"][0]["after"]
    assert created["stock_quantity"] == "0.000"
    assert StockMovement.query.filter_by(stock_item_id=created["id"]).count() == 0
    assert db.session.get(StockItem, unrelated["id"]).stock_quantity == 50
    assert AuditLog.query.filter_by(action="stock.photo_import").count() == 1


def test_audit_api_presents_readable_import_and_stock_labels(client, admin_session):
    h = admin_session["headers"]
    body = source()
    assert apply(client, h, confirmation(body, preview(client, h, body))).status_code == 200
    response = client.get("/api/audit", headers=h)
    assert response.status_code == 200
    rows = response.get_json()["data"]["items"]
    labels = {r["action"]: (r["action_label"], r["entity_label"]) for r in rows}
    assert labels["stock.photo_import"] == ("导入照片盘点", "库存盘点来源")
    assert labels["stock.photo_count"] == ("照片盘点调整", "库存流水")


def test_equal_existing_target_has_receipt_without_movement_or_version_change(client, admin_session):
    h = admin_session["headers"]
    item = master(client, h, "800")
    body = source(mapping={"1": {"stock_item_id": item["id"]}})
    request = confirmation(body, preview(client, h, body))
    response = apply(client, h, request)
    assert response.status_code == 200
    row = response.get_json()["data"]["rows"][0]
    assert row["movement_id"] is None and row["after"]["version"] == item["version"]
    assert StockMovement.query.filter_by(movement_type="photo_count").count() == 0


def test_source_digest_preserves_bom_and_recomputed_changed_source_cannot_reuse_preview(client, admin_session):
    h = admin_session["headers"]
    raw = b"\xef\xbb\xbf" + BOXES.replace("\n", "\r\n").encode("utf-8")
    body = source(raw)
    result = preview(client, h, body)
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    tampered = confirmation(source(BOXES.replace(",4,800,", ",5,1000,")), result)
    assert apply(client, h, tampered).status_code == 409
    assert StockMovement.query.filter_by(movement_type="photo_count").count() == 0


def test_missing_request_id_is_rejected(client, admin_session):
    h = admin_session["headers"]
    body = source()
    result = preview(client, h, body)
    r = client.post(ROOT + "/apply", headers=h, json=confirmation(body, result))
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "IDEMPOTENCY_REQUIRED"


def test_ready_row_cannot_infer_explicitly_blank_original_evidence(client, admin_session):
    csv = HEADER.rstrip("\n") + ",original_quantity,original_unit,input_unit\n"
    csv += BOXES.splitlines()[1] + ",,,\n"
    r = client.post(ROOT + "/preview", headers=admin_session["headers"], json=source(csv))
    assert r.status_code == 400


def test_reviewed_photo_csv_preserves_43_rows_with_16_ready_27_excluded(client, admin_session):
    raw = (Path(__file__).parents[2] / "docs/inventory/2026-10-05-photo-stock-review.csv").read_bytes()
    ready = ["1", "2", "3", "5", "7", "9", "10", "19", "20", "21", "25", "36", "38", "39", "41", "43"]
    body = source(raw, {n: {"create": True} for n in ready})
    result = preview(client, admin_session["headers"], body)
    assert result["summary"] == {"evidence_rows": 43, "ready_rows": 16, "excluded_rows": 27}
    rows = {r["row"]: r for r in result["rows"]}
    assert rows["1"]["target_quantity"] == "800.000"
    assert rows["10"]["target_quantity"] == "400.000" and rows["10"]["input_unit"] == "袋"
    assert rows["25"]["target_quantity"] == "12.000" and rows["25"]["base_unit"] == "支"
    assert rows["38"]["target_quantity"] == "3.000" and rows["38"]["base_unit"] == "桶"
    assert rows["39"]["target_quantity"] == "800.000" and rows["39"]["input_unit"] == "条"
    assert {r["row"] for r in result["excluded"]} >= {"22", "23", "24", "26", "27", "28", "42"}
    response = apply(client, admin_session["headers"], confirmation(body, result))
    assert response.status_code == 200, response.get_json()
    assert len(response.get_json()["data"]["rows"]) == 16


@pytest.mark.parametrize("change", ["hash", "mapping", "period", "digest", "source", "confirmation"])
def test_tampered_confirmation_fails_even_after_successful_generic_retry(client, admin_session, change):
    h = admin_session["headers"]
    body = source()
    request = confirmation(body, preview(client, h, body))
    assert apply(client, h, request).status_code == 200
    if change == "hash":
        request["source_sha256"] = "0" * 64
    elif change == "mapping":
        request["mapping"] = {"1": {"stock_item_id": StockItem.query.filter_by(name="奶浴袋").one().id}}
    elif change == "period":
        request["period_id"] = "different-period"
    elif change == "digest":
        request["preview_digest"] = "0" * 64
    elif change == "source":
        request["source_base64"] = source(BOXES.replace("800", "900"))["source_base64"]
    else:
        request["confirm"] = False
    for key in ("photo-count", "new-key"):
        response = apply(client, h, request, key)
        assert response.status_code in {400, 409}, response.get_json()
    assert StockItem.query.filter_by(name="奶浴袋").count() == 1
    assert StockMovement.query.filter_by(movement_type="photo_count").count() == 1


@pytest.mark.parametrize("change", ["balance", "version", "unit", "mapping", "period"])
def test_preview_staleness_rejected_atomically(client, admin_session, change):
    h = admin_session["headers"]
    item = master(client, h)
    body = source(mapping={"1": {"stock_item_id": item["id"]}})
    request = confirmation(body, preview(client, h, body))
    row = db.session.get(StockItem, item["id"])
    if change == "balance":
        row.stock_quantity = 49
    elif change == "version":
        row.version += 1
    elif change == "unit":
        row.base_unit = "条"
    elif change == "mapping":
        request["mapping"] = {"1": {"create": True}}
    else:
        period = BusinessPeriod()
        db.session.add(period)
        db.session.flush()
        db.session.get(BusinessStateModel, 1).period_id = period.id
    db.session.commit()
    response = apply(client, h, request)
    assert response.status_code == 409, response.get_json()
    assert AuditLog.query.filter_by(action="stock.photo_import").count() == 0


@pytest.mark.parametrize(
    "csv,mapping",
    [
        (BOXES + "photo2,1,重复,默认,袋,箱,200,4,800,ready\n", {"1": {"create": True}}),
        (BOXES.replace(",袋,", ",未知,"), {"1": {"create": True}}),
        (BOXES.replace(",箱,", ",?,"), {"1": {"create": True}}),
        (BOXES.replace(",800,", ",799,"), {"1": {"create": True}}),
        (BOXES.replace(",200,4,800,", ",0.001,0.001,0.000001,"), {"1": {"create": True}}),
        (BOXES.replace(",200,4,800,", ",200,5000000,1000000000,"), {"1": {"create": True}}),
        (BOXES, {}),
        (BOXES, {"1": {"create": "yes"}}),
    ],
)
def test_reject_invalid_units_conversion_overlap_or_unconfirmed_mapping(client, admin_session, csv, mapping):
    r = client.post(ROOT + "/preview", headers=admin_session["headers"], json=source(csv, mapping))
    assert r.status_code == 400, r.get_json()


def test_duplicate_target_rejected_and_unresolved_rows_excluded(client, admin_session):
    h = admin_session["headers"]
    item = master(client, h)
    csv = BOXES + "photo1,2,第二行,默认,袋,箱,200,4,800,ready\n"
    r = client.post(
        ROOT + "/preview",
        headers=h,
        json=source(csv, {"1": {"stock_item_id": item["id"]}, "2": {"stock_item_id": item["id"]}}),
    )
    assert r.status_code == 400
    body = source(BOXES + "photo2,22,未确认,默认,,箱,200,4,,needs_base_unit\n")
    result = preview(client, h, body)
    assert result["summary"]["excluded_rows"] == 1
    assert result["excluded"][0]["evidence"]["base_unit"] == ""


def test_late_stock_failure_rolls_back_master_movement_and_audit(client, admin_session, monkeypatch):
    import app.stock_import as service
    from app.api.errors import ApiError

    h = admin_session["headers"]
    csv = BOXES + "photo1,2,第二行,默认,条,箱,100,2,200,ready\n"
    body = source(csv, {"1": {"create": True}, "2": {"create": True}})
    request = confirmation(body, preview(client, h, body))
    original = service.change_balance

    def second_fails(master, *args, **kwargs):
        if master.name == "第二行":
            raise ApiError("simulated concurrent failure", 409)
        return original(master, *args, **kwargs)

    monkeypatch.setattr(service, "change_balance", second_fails)
    r = apply(client, h, request)
    assert r.status_code == 409
    assert StockItem.query.filter(StockItem.name.in_(["奶浴袋", "第二行"])).count() == 0
    assert StockMovement.query.filter_by(movement_type="photo_count").count() == 0
    assert AuditLog.query.filter_by(action="stock.photo_count").count() == 0
    assert AuditLog.query.filter_by(action="stock.photo_import").count() == 0
    assert verify_audit_chain() == (True, None)


def test_global_receipt_survives_business_period_change(client, admin_session):
    h = admin_session["headers"]
    body = source()
    request = confirmation(body, preview(client, h, body))
    first = apply(client, h, request).get_json()["data"]
    period = BusinessPeriod()
    db.session.add(period)
    db.session.flush()
    db.session.get(BusinessStateModel, 1).period_id = period.id
    db.session.commit()
    again = apply(client, h, request, "new-period-request")
    assert again.status_code == 200 and again.get_json()["data"] == first
    assert StockItem.query.filter_by(name="奶浴袋").count() == 1
    assert AuditLog.query.filter_by(action="stock.photo_import").count() == 1


def test_new_actor_replay_does_not_restore_stock_consumed_since_import(client, strict_owner_session):
    h = strict_owner_session["headers"]
    body = source()
    request = confirmation(body, preview(client, h, body))
    first = apply(client, h, request).get_json()["data"]
    stock = first["rows"][0]["after"]
    r = client.post(
        "/api/inventory/stock-adjust",
        headers={**h, "Idempotency-Key": "subsequent-loss"},
        json={
            "stock_item_id": stock["id"],
            "version": stock["version"],
            "movement_type": "loss",
            "quantity": "1",
            "input_unit": "base",
            "reason": "盘点后的耗损",
        },
    )
    assert r.status_code == 200
    r = client.post(
        "/api/employees",
        headers=h,
        json={
            "username": "other-importer",
            "display_name": "另一库管",
            "role": "inventory",
            "password": "fixture-import-2026",
            "allowed_channels": ["desktop"],
        },
    )
    assert r.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={
            "username": "other-importer",
            "password": "fixture-import-2026",
            "terminal_code": "ENTRY-TEST",
            "client_channel": "desktop",
        },
    ).get_json()["data"]
    other = {
        "Authorization": "Bearer " + login["access_token"],
        "X-Business-Period": login["business_state"]["period_id"],
    }
    repeated = apply(client, other, request, "different-actor")
    assert repeated.status_code == 200 and repeated.get_json()["data"] == first
    assert db.session.get(StockItem, stock["id"]).stock_quantity == 799
    assert StockMovement.query.filter_by(movement_type="photo_count").count() == 1
    assert preview(client, other, body)["already_applied_receipt_id"] == first["receipt_id"]


@pytest.mark.parametrize("role,status", [("cashier", 200), ("inventory", 200), ("male_scrubber", 403)])
def test_authenticated_inventory_capability_and_period_guard(client, strict_owner_session, role, status):
    owner = strict_owner_session
    r = client.post(
        "/api/employees",
        headers=owner["headers"],
        json={
            "username": "import-" + role,
            "display_name": role,
            "role": role,
            "password": "fixture-import-2026",
            "allowed_channels": ["desktop"],
        },
    )
    assert r.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={
            "username": "import-" + role,
            "password": "fixture-import-2026",
            "terminal_code": "ENTRY-TEST",
            "client_channel": "desktop",
        },
    ).get_json()["data"]
    h = {"Authorization": "Bearer " + login["access_token"], "X-Business-Period": login["business_state"]["period_id"]}
    body = source()
    r = client.post(ROOT + "/preview", headers=h, json=body)
    assert r.status_code == status, r.get_json()
    if status == 200:
        request = confirmation(body, r.get_json()["data"])
        assert apply(client, {**h, "X-Business-Period": "stale"}, request).status_code == 409
        assert apply(client, h, request).status_code == 200
    else:
        assert apply(client, h, {**body, "confirm": True}).status_code == 403
