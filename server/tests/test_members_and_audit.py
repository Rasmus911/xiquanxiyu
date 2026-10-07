from datetime import datetime, timedelta
from types import SimpleNamespace

from app import sms_service
from app.models import MemberPass, PassLedger


def test_member_recharge_and_pass(client, admin_session):
    headers = admin_session["headers"]
    created = client.post("/api/members", json={"phone": "138-0000-0000", "name": "测试会员"}, headers=headers)
    assert created.status_code == 201
    member = created.get_json()["data"]
    recharge = client.post(
        f"/api/members/{member['id']}/recharge",
        json={"amount": 100, "payment_method": "cash", "idempotency_key": "recharge-1"},
        headers={**headers, "Idempotency-Key": "recharge-1"},
    )
    assert recharge.status_code == 200
    assert recharge.get_json()["data"]["balance"] == "100.00"
    issued = client.post(
        f"/api/members/{member['id']}/passes",
        json={
            "name": "十次卡",
            "count": 10,
            "amount": 300,
            "payment_method": "wechat",
            "idempotency_key": "member-pass-1",
        },
        headers={**headers, "Idempotency-Key": "member-pass-1"},
    )
    assert issued.status_code == 201
    member_pass = issued.get_json()["data"]
    consumed = client.post(
        f"/api/members/passes/{member_pass['id']}/consume",
        json={},
        headers={**headers, "Idempotency-Key": "member-consume-1"},
    )
    assert consumed.status_code == 200
    assert consumed.get_json()["data"]["remaining_count"] == 9

    member_rows = client.get("/api/members", headers=headers).get_json()["data"]
    member_summary = next(row for row in member_rows if row["id"] == member["id"])
    assert member_summary["has_stored_value"] is True
    assert member_summary["has_pass"] is True
    assert member_summary["active_pass_count"] == 1
    assert member_summary["pass_remaining"] == 9

    exact_lookup = client.get("/api/members/lookup", query_string={"phone": "13800000000"}, headers=headers)
    assert exact_lookup.status_code == 200
    assert exact_lookup.get_json()["data"]["id"] == member["id"]
    partial_lookup = client.get("/api/members/lookup", query_string={"phone": "1380000"}, headers=headers)
    assert partial_lookup.status_code == 400

    bands = client.get("/api/wristbands", headers=headers).get_json()["data"]
    band = next(row for row in bands if row["number"] == "8001")
    visit = client.post(f"/api/wristbands/{band['id']}/open", json={}, headers=headers).get_json()["data"]
    services = client.get("/api/catalog", headers=headers).get_json()["data"]
    service = next(row for row in services if row["name"] == "传统搓澡")
    client.post(
        f"/api/visits/{visit['id']}/items",
        json={"catalog_item_id": service["id"], "quantity": 1},
        headers=headers,
    )
    checkout = client.post(
        "/api/checkout",
        json={
            "visit_ids": [visit["id"]],
            "member_id": member["id"],
            "payments": [{"method": "balance", "amount": 30}],
            "idempotency_key": "member-balance-checkout",
        },
        headers={**headers, "Idempotency-Key": "member-balance-checkout"},
    )
    assert checkout.status_code == 201

    start = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    report = client.get("/api/reports/summary", query_string={"start": start, "end": end}, headers=headers)
    summary = report.get_json()["data"]
    assert summary["operating_revenue"] == "30.00"
    assert summary["stored_value_recharge"] == "100.00"
    assert summary["pass_card_sales"] == "300.00"
    assert summary["member_recharge"] == "400.00"
    assert summary["stored_value_consumed"] == "30.00"
    assert summary["actual_cash_inflow"] == "400.00"


def test_paid_pass_card_is_idempotent_and_reported_once(app, client, admin_session):
    headers = admin_session["headers"]
    member = client.post(
        "/api/members",
        json={"phone": "13700000000", "name": "次卡收款测试"},
        headers=headers,
    ).get_json()["data"]
    payload = {
        "name": "洗浴10次卡",
        "count": 10,
        "amount": 300,
        "payment_method": "wechat",
        "valid_until": None,
        "note": "测试售卡",
        "idempotency_key": "paid-pass-300",
    }
    request_headers = {**headers, "Idempotency-Key": "paid-pass-300"}

    first = client.post(f"/api/members/{member['id']}/passes", json=payload, headers=request_headers)
    repeated = client.post(f"/api/members/{member['id']}/passes", json=payload, headers=request_headers)

    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.get_json()["data"]["id"] == first.get_json()["data"]["id"]
    with app.app_context():
        assert MemberPass.query.filter_by(member_id=member["id"]).count() == 1
        ledger = PassLedger.query.filter_by(idempotency_key="paid-pass-300").one()
        assert ledger.delta == 10
        assert ledger.balance_after == 10
        assert ledger.amount_paid == 300
        assert ledger.payment_method == "wechat"

    start = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    summary = client.get(
        "/api/reports/summary",
        query_string={"start": start, "end": end},
        headers=headers,
    ).get_json()["data"]
    assert summary["pass_card_sales"] == "300.00"
    assert summary["stored_value_recharge"] == "0.00"
    assert summary["member_recharge"] == "300.00"
    assert summary["actual_cash_inflow"] == "300.00"


def test_default_male_and_female_wristbands(client, admin_session):
    rows = client.get("/api/wristbands", headers=admin_session["headers"]).get_json()["data"]
    male = [row for row in rows if row["bath_area"] == "male"]
    female = [row for row in rows if row["bath_area"] == "female"]
    assert len(male) == 60
    assert len(female) == 60
    assert {row["number"] for row in male} == {str(number) for number in range(8001, 8061)}
    assert {row["number"] for row in female} == {str(number) for number in range(9001, 9061)}
    catalog = client.get("/api/catalog", headers=admin_session["headers"]).get_json()["data"]
    names = {row["name"] for row in catalog}
    assert {
        "传统搓澡",
        "一次性搓澡巾",
        "牛奶浴",
        "盐浴",
        "芦荟浴",
        "二合一（搓澡+牛奶）",
        "三合一（搓澡+牛奶+盐）",
        "承德杏仁露",
    } <= names


def test_card_opening_sms_only_on_first_recharge_and_each_new_pass(client, admin_session, monkeypatch):
    headers = admin_session["headers"]
    calls = []

    def fake_notify(member, employee, card_type, **details):
        calls.append(
            {
                "member_phone": member.phone,
                "employee": employee.username,
                "card_type": card_type,
                **details,
            }
        )
        return [
            {"recipient": "member", "success": True, "status": "sent", "message": "已提交"},
            {"recipient": "admin", "success": True, "status": "sent", "message": "已提交"},
        ]

    monkeypatch.setattr("app.api.members.notify_card_opened", fake_notify)
    member = client.post(
        "/api/members",
        json={"phone": "13900000000", "name": "张三"},
        headers=headers,
    ).get_json()["data"]

    first_recharge = client.post(
        f"/api/members/{member['id']}/recharge",
        json={"amount": 100, "payment_method": "cash", "idempotency_key": "sms-recharge-1"},
        headers={**headers, "Idempotency-Key": "sms-recharge-1"},
    )
    assert first_recharge.status_code == 200
    assert len(first_recharge.get_json()["data"]["sms_notifications"]) == 2

    second_recharge = client.post(
        f"/api/members/{member['id']}/recharge",
        json={"amount": 50, "payment_method": "wechat", "idempotency_key": "sms-recharge-2"},
        headers={**headers, "Idempotency-Key": "sms-recharge-2"},
    )
    assert second_recharge.status_code == 200
    assert "sms_notifications" not in second_recharge.get_json()["data"]

    pass_response = client.post(
        f"/api/members/{member['id']}/passes",
        json={"name": "十次卡", "count": 10, "amount": 300, "payment_method": "cash", "idempotency_key": "sms-pass-1"},
        headers={**headers, "Idempotency-Key": "sms-pass-1"},
    )
    assert pass_response.status_code == 201
    assert len(pass_response.get_json()["data"]["sms_notifications"]) == 2
    assert [row["card_type"] for row in calls] == ["stored", "pass"]
    assert calls[0]["balance"] == "100.00"
    assert calls[1]["remaining"] == 10
    assert calls[1]["total"] == 10


def test_card_sms_template_parameters(app, monkeypatch):
    sent = []

    def fake_send(phone, template_code, template_params, recipient):
        sent.append((phone, template_code, template_params, recipient))
        return {"recipient": recipient, "success": True, "status": "sent", "message": "已提交"}

    monkeypatch.setattr(sms_service, "send_template_sms", fake_send)
    with app.app_context():
        app.config.update(
            SMS_ADMIN_PHONE="18631459666",
            SMS_STORED_CARD_TEMPLATE_CODE="SMS_STORED",
            SMS_PASS_CARD_TEMPLATE_CODE="SMS_PASS",
            SMS_ADMIN_TEMPLATE_CODE="SMS_ADMIN",
        )
        member = SimpleNamespace(phone="13900000000", name="张三")
        employee = SimpleNamespace(username="cashier01", display_name="收银员")
        sms_service.notify_card_opened(member, employee, "stored", balance="188.00")
        sms_service.notify_card_opened(member, employee, "pass", remaining=8, total=10)

    assert sent[0] == ("13900000000", "SMS_STORED", {"balance": "188.00"}, "member")
    assert sent[1] == (
        "18631459666",
        "SMS_ADMIN",
        {"employee": "cashier01员工", "member": "张三"},
        "admin",
    )
    assert sent[2] == (
        "13900000000",
        "SMS_PASS",
        {"remaining": "8", "total": "10"},
        "member",
    )


def test_audit_chain(client, admin_session):
    headers = admin_session["headers"]
    audit_response = client.get("/api/audit", query_string={"employee": "admin", "action": "登录"}, headers=headers)
    assert audit_response.status_code == 200
    audit_rows = audit_response.get_json()["data"]["items"]
    assert audit_rows
    assert all(row["employee_id"] == "admin" for row in audit_rows)
    assert any(row["action_label"] == "员工登录" for row in audit_rows)

    verified = client.get("/api/audit/verify", headers=headers)
    assert verified.status_code == 200
    assert verified.get_json()["data"]["valid"] is True
