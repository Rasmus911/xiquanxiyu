"""CLI uses authenticated HTTP on loopback, hidden credentials, explicit review."""

import hashlib
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location(
        "photo_import_cli", Path(__file__).parents[2] / "scripts/stock_import.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def http_api():
    calls = []
    state = {"fail": None, "redirect": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, body, dict(self.headers)))
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "/capture-password")
                self.end_headers()
                return
            if state["fail"]:
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"success": False, "message": "password-secret token-secret", "error": {"code": state["fail"]}}
                    ).encode()
                )
                return
            if self.path == "/api/auth/login":
                assert body["password"] == "password-secret" and body["client_channel"] == "desktop"
                data = {
                    "access_token": "token-secret",
                    "refresh_token": "unused-secret",
                    "business_state": {"period_id": "period-1"},
                }
            else:
                assert self.headers["Authorization"] == "Bearer token-secret"
                assert self.headers["X-Business-Period"] == "period-1"
                if self.path.endswith("/preview"):
                    data = {
                        "source_sha256": body["source_sha256"],
                        "period_id": "period-1",
                        "mapping": body["mapping"],
                        "summary": {"evidence_rows": 1, "ready_rows": 1, "excluded_rows": 0},
                        "rows": [
                            {
                                "row": "1",
                                "input_quantity": "4.000",
                                "input_unit": "箱",
                                "base_unit": "袋",
                                "target_quantity": "800.000",
                                "delta": "750.000",
                                "before": {"stock_quantity": "50.000", "version": 1},
                            }
                        ],
                        "excluded": [],
                    }
                    data["preview_digest"] = hashlib.sha256(
                        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()
                    state["preview_digest"] = data["preview_digest"]
                else:
                    assert self.path.endswith("/apply") and body["confirm"] is True
                    assert body["preview_digest"] == state["preview_digest"] and self.headers["Idempotency-Key"]
                    data = {"receipt_id": "receipt-1", "source_sha256": body["source_sha256"], "rows": []}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "data": data, "message": "ok", "request_id": "r-1"}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api", calls, state
    server.shutdown()
    thread.join()
    server.server_close()


def args(url):
    return ["--api-url", url, "--username", "fixture", "--terminal-code", "REGISTERED"]


def inputs(tmp_path):
    csv = tmp_path / "review.csv"
    csv.write_bytes(b"fixture-exact-UTF8-bytes\r\n")
    mapping = tmp_path / "mapping.json"
    mapping.write_text('{"1":{"create":true}}')
    return csv, mapping, tmp_path / "preview.json", tmp_path / "receipt.json"


def test_cli_preview_apply_uses_hidden_login_http_and_never_persists_credentials(
    cli, http_api, tmp_path, monkeypatch, capsys
):
    url, calls, _ = http_api
    csv, mapping, reviewed, receipt = inputs(tmp_path)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "password-secret")
    assert (
        cli.main(args(url) + ["preview", "--csv", str(csv), "--mapping", str(mapping), "--output", str(reviewed)]) == 0
    )
    preview = json.loads(reviewed.read_text(encoding="utf-8"))
    monkeypatch.setattr("builtins.input", lambda _: "APPLY " + preview["preview"]["source_sha256"])
    assert (
        cli.main(
            args(url)
            + [
                "apply",
                "--csv",
                str(csv),
                "--mapping",
                str(mapping),
                "--preview",
                str(reviewed),
                "--output",
                str(receipt),
            ]
        )
        == 0
    )
    assert [x[0] for x in calls] == [
        "/api/auth/login",
        "/api/inventory/photo-import/preview",
        "/api/auth/login",
        "/api/inventory/photo-import/apply",
    ]
    assert calls[1][1]["source_base64"] == "Zml4dHVyZS1leGFjdC1VVEY4LWJ5dGVzDQo="
    assert calls[-1][1]["source_sha256"] == preview["preview"]["source_sha256"]
    captured = capsys.readouterr()
    output = captured.out + captured.err + reviewed.read_text(encoding="utf-8") + receipt.read_text(encoding="utf-8")
    assert "800.000" in output and "箱" in output and "袋" in output
    assert "password-secret" not in output and "token-secret" not in output and "unused-secret" not in output


@pytest.mark.parametrize("changed", ["csv", "mapping", "api", "decline"])
def test_cli_stops_before_apply_on_changed_review_or_declined_confirmation(
    cli, http_api, tmp_path, monkeypatch, changed
):
    url, calls, _ = http_api
    csv, mapping, reviewed, receipt = inputs(tmp_path)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "password-secret")
    assert (
        cli.main(args(url) + ["preview", "--csv", str(csv), "--mapping", str(mapping), "--output", str(reviewed)]) == 0
    )
    if changed == "csv":
        csv.write_bytes(b"changed")
    elif changed == "mapping":
        mapping.write_text('{"1":{"stock_item_id":"other"}}')
    elif changed == "api":
        data = json.loads(reviewed.read_text(encoding="utf-8"))
        data["api_url"] = "https://other.example/api"
        reviewed.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert (
        cli.main(
            args(url)
            + [
                "apply",
                "--csv",
                str(csv),
                "--mapping",
                str(mapping),
                "--preview",
                str(reviewed),
                "--output",
                str(receipt),
            ]
        )
        != 0
    )
    assert not any(x[0].endswith("/apply") for x in calls)
    assert not receipt.exists()


def test_cli_transport_error_redacts_remote_echo_and_never_follows_login_redirect(
    cli, http_api, tmp_path, monkeypatch, capsys
):
    url, calls, state = http_api
    csv, mapping, reviewed, _ = inputs(tmp_path)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "password-secret")
    command = args(url) + ["preview", "--csv", str(csv), "--mapping", str(mapping), "--output", str(reviewed)]
    state["fail"] = "STOCK_IMPORT_STALE"
    assert cli.main(command) != 0
    state["fail"] = None
    state["redirect"] = True
    assert cli.main(command) != 0
    assert [x[0] for x in calls] == ["/api/auth/login", "/api/auth/login"]
    captured = capsys.readouterr()
    assert "password-secret" not in captured.err + captured.out
    assert "token-secret" not in captured.err + captured.out
    assert not reviewed.exists()


@pytest.mark.parametrize("changed", ["target_quantity", "delta", "before_quantity", "before_version"])
def test_cli_rejects_edited_preview_before_display_confirmation_or_http(
    cli, http_api, tmp_path, monkeypatch, capsys, changed
):
    url, calls, _ = http_api
    csv, mapping, reviewed, receipt = inputs(tmp_path)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "password-secret")
    assert (
        cli.main(args(url) + ["preview", "--csv", str(csv), "--mapping", str(mapping), "--output", str(reviewed)]) == 0
    )
    document = json.loads(reviewed.read_text(encoding="utf-8"))
    row = document["preview"]["rows"][0]
    if changed == "before_quantity":
        row["before"]["stock_quantity"] = "5.000"
    elif changed == "before_version":
        row["before"]["version"] = 99
    else:
        row[changed] = "8.000"
    reviewed.write_text(json.dumps(document), encoding="utf-8")
    prompts = []

    def confirm(prompt):
        prompts.append(prompt)
        return "APPLY " + document["preview"]["source_sha256"]

    monkeypatch.setattr("builtins.input", confirm)
    capsys.readouterr()
    assert (
        cli.main(
            args(url)
            + [
                "apply",
                "--csv",
                str(csv),
                "--mapping",
                str(mapping),
                "--preview",
                str(reviewed),
                "--output",
                str(receipt),
            ]
        )
        != 0
    )
    assert capsys.readouterr().out == ""
    assert prompts == []
    assert [call[0] for call in calls] == ["/api/auth/login", "/api/inventory/photo-import/preview"]
    assert not receipt.exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/api",
        "https://user:pass@example.com/api",
        "https://example.com/api?token=secret",
        "file:///tmp/api",
    ],
)
def test_cli_rejects_unsafe_endpoint_before_prompt_or_transport(cli, url, tmp_path, monkeypatch):
    csv, mapping, reviewed, _ = inputs(tmp_path)

    def forbidden(_):
        pytest.fail("credentials must not be requested for an unsafe URL")

    monkeypatch.setattr(cli.getpass, "getpass", forbidden)
    assert (
        cli.main(args(url) + ["preview", "--csv", str(csv), "--mapping", str(mapping), "--output", str(reviewed)]) != 0
    )


def test_cli_real_flask_http_round_trip_with_strict_policy(cli, app, strict_owner_session, tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from app.audit_service import verify_audit_chain
    from app.extensions import db
    from app.models import StockItem, StockMovement

    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api"
    csv, mapping, reviewed, receipt = inputs(tmp_path)
    csv.write_text(
        "source_photo,row,name,category,base_unit,package_unit,units_per_package,package_quantity,basic_quantity,review_status\n"
        "photo1,1,真实HTTP盘点,搓澡耗材,袋,箱,200,4,800,ready\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: strict_owner_session["password"])
    common = ["--api-url", url, "--username", "fixture-owner", "--terminal-code", "ENTRY-TEST"]
    try:
        listing = tmp_path / "stock-ids.json"
        assert cli.main(common + ["list", "--output", str(listing)]) == 0
        assert isinstance(json.loads(listing.read_text(encoding="utf-8"))["stock_items"], list)
        assert (
            cli.main(common + ["preview", "--csv", str(csv), "--mapping", str(mapping), "--output", str(reviewed)]) == 0
        )
        saved = json.loads(reviewed.read_text(encoding="utf-8"))
        monkeypatch.setattr("builtins.input", lambda _: "APPLY " + saved["preview"]["source_sha256"])
        command = common + ["apply", "--csv", str(csv), "--mapping", str(mapping), "--preview", str(reviewed)]
        assert cli.main(command + ["--output", str(receipt)]) == 0
        second = tmp_path / "replayed-receipt.json"
        assert cli.main(command + ["--output", str(second)]) == 0
        assert json.loads(receipt.read_text(encoding="utf-8")) == json.loads(second.read_text(encoding="utf-8"))
        # A fresh preview of an already-applied source has one unsigned replay marker.
        replay_preview = tmp_path / "replay-preview.json"
        assert (
            cli.main(
                common + ["preview", "--csv", str(csv), "--mapping", str(mapping), "--output", str(replay_preview)]
            )
            == 0
        )
        replay_document = json.loads(replay_preview.read_text(encoding="utf-8"))
        assert replay_document["preview"]["already_applied_receipt_id"]
        third = tmp_path / "fresh-preview-receipt.json"
        assert (
            cli.main(
                common
                + [
                    "apply",
                    "--csv",
                    str(csv),
                    "--mapping",
                    str(mapping),
                    "--preview",
                    str(replay_preview),
                    "--output",
                    str(third),
                ]
            )
            == 0
        )
        assert json.loads(receipt.read_text(encoding="utf-8")) == json.loads(third.read_text(encoding="utf-8"))
        db.session.expire_all()
        assert str(StockItem.query.filter_by(name="真实HTTP盘点").one().stock_quantity) == "800.000"
        assert StockMovement.query.filter_by(movement_type="photo_count").count() == 1
        assert verify_audit_chain() == (True, None)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
