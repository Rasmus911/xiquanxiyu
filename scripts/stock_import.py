"""Human-reviewed photo inventory HTTP client (standard library only).

No direct database access, password/token flags, signing, or cloud automation.
"""

import argparse
import base64
import getpass
import hashlib
import json
import sys
import uuid
import warnings
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ImportClientError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # In particular, never forward login credentials or bearer tokens.
        raise ImportClientError("HTTP重定向已拒绝，请核对API地址")


def api_url(value):
    parsed = urlsplit(value)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/api"
        or not (parsed.scheme == "https" or parsed.scheme == "http" and loopback)
    ):
        raise ImportClientError("API地址必须为HTTPS且以/api结尾，不含凭据、查询或片段；仅本机测试可用HTTP")
    return value.rstrip("/")


def request_json(url, body=None, headers=None):
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as error:
        # Remote messages may reflect submitted credentials. Log only status.
        raise ImportClientError("HTTP请求失败，状态码" + str(error.code) + "；未自动重试") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ImportClientError("连接或响应无效；未自动重试，请保留核对文件") from None
    if not isinstance(payload, dict) or payload.get("success") is not True or "data" not in payload:
        raise ImportClientError("API未返回有效成功结果")
    return payload["data"]


def login(url, username, terminal):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            password = getpass.getpass("当前账号登录密码（隐藏输入）：")
        except getpass.GetPassWarning:
            raise ImportClientError("当前终端不支持隐藏输入，请使用交互式PowerShell") from None
    result = request_json(
        url + "/auth/login",
        {"username": username, "password": password, "terminal_code": terminal, "client_channel": "desktop"},
    )
    del password
    if not isinstance(result, dict) or not isinstance(result.get("access_token"), str):
        raise ImportClientError("登录响应缺少访问凭据")
    period = result.get("business_state", {}).get("period_id")
    if not isinstance(period, str) or not period:
        raise ImportClientError("登录响应缺少经营期")
    return {"Authorization": "Bearer " + result["access_token"], "X-Business-Period": period}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def source_body(csv_path, mapping_path):
    raw = Path(csv_path).read_bytes()
    if len(raw) > 260000:
        raise ImportClientError("CSV文件过大")
    raw.decode("utf-8-sig")
    mapping = load_json(mapping_path)
    if not isinstance(mapping, dict):
        raise ImportClientError("映射文件必须为JSON对象")
    return {
        "source_base64": base64.b64encode(raw).decode("ascii"),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "mapping": mapping,
    }


def show(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def save(path, value):
    # Preserve previous evidence; reruns use a fresh output filename.
    with Path(path).open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="照片库存盘点：先保存核对预览，再明确确认目标余额")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--terminal-code", required=True, help="已注册并启用的桌面终端代码")
    subparsers = parser.add_subparsers(dest="command", required=True)
    listing = subparsers.add_parser("list", help="列出库存稳定ID、单位、余额和版本以便人工映射")
    listing.add_argument("--output", required=True)
    for command in ("preview", "apply"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--csv", required=True)
        command_parser.add_argument("--mapping", required=True)
        command_parser.add_argument("--output", required=True)
        if command == "apply":
            command_parser.add_argument("--preview", required=True)
    options = parser.parse_args(argv)
    try:
        url = api_url(options.api_url)
        output = Path(options.output)
        if output.exists() or not output.parent.is_dir():
            raise ImportClientError("输出文件必须是已存在目录中的新文件，请保留原有核对证据")
        if options.command != "list":
            body = source_body(options.csv, options.mapping)
        if options.command == "apply":
            reviewed = load_json(options.preview)
            saved = reviewed["preview"]
            if (
                reviewed["api_url"] != url
                or saved["source_sha256"] != body["source_sha256"]
                or saved["mapping"] != body["mapping"]
            ):
                raise ImportClientError("CSV、映射或API已变化；必须重新预览和审核")
            # Match the server's canonical digest; the replay marker is added only
            # after the original confirmed preview has been stored in its receipt.
            content = {
                key: value
                for key, value in saved.items()
                if key not in {"preview_digest", "already_applied_receipt_id"}
            }
            actual_digest = hashlib.sha256(
                json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if actual_digest != saved["preview_digest"]:
                raise ImportClientError("预览内容与摘要不一致；必须重新获取预览并审核")
            show(saved)
            expected = "APPLY " + body["source_sha256"]
            if input("核对全部行、排除项和前后余额后，输入 " + expected + "：").strip() != expected:
                raise ImportClientError("未确认，未提交盘点")
            body.update(confirm=True, preview_digest=saved["preview_digest"], period_id=saved["period_id"])
        headers = login(url, options.username, options.terminal_code)
        if options.command == "list":
            result = request_json(url + "/inventory/stock-items?include_inactive=true", headers=headers)
            document = {"api_url": url, "stock_items": result}
        elif options.command == "preview":
            result = request_json(url + "/inventory/photo-import/preview", body, headers)
            document = {"api_url": url, "preview": result}
        else:
            result = request_json(
                url + "/inventory/photo-import/apply", body, {**headers, "Idempotency-Key": str(uuid.uuid4())}
            )
            document = {"api_url": url, "receipt": result}
        save(output, document)
        show(document)
        return 0
    except ImportClientError as error:
        print(str(error), file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        print("本地核对文件、终端输入或响应结构无效；请保留预览和文件摘要后检查", file=sys.stderr)
    except KeyboardInterrupt:
        print("操作中断；如已发出请求，请使用原CSV、映射及预览重试以获取原回执", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
