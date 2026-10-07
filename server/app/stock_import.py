"""Reviewed photo counts; caller owns authorization, serialization and commit.

AuditLog is deliberately period-independent: a reset must not make a previously
imported source look new. No name matching or procurement-price interpretation.
"""

import base64
import binascii
import csv
import hashlib
import io
import json
import re
from decimal import Decimal

from .api.errors import ApiError
from .audit_service import write_audit
from .business_period import current_period_id
from .extensions import db
from .models import AuditLog, StockItem, new_uuid
from .serializers import stock_item_dict
from .stock_service import change_balance, stock_quantity

REQUIRED = {
    "source_photo",
    "row",
    "name",
    "category",
    "base_unit",
    "package_unit",
    "units_per_package",
    "package_quantity",
    "basic_quantity",
    "review_status",
}
OPTIONAL = {"package_spec", "original_quantity", "original_unit", "input_unit", "notes"}
UNITS = {"袋", "瓶", "条", "个", "套", "块", "支", "桶", "卷", "包", "盒", "件", "箱", "升", "毫升", "克", "千克"}
SOURCE_FIELDS = {"source_base64", "source_sha256", "mapping"}
CONFIRM_FIELDS = {"confirm", "preview_digest", "period_id"}


def invalid(message):
    raise ApiError(message, 400, "INVALID_STOCK_IMPORT")


def stale():
    raise ApiError("盘点预览或映射已变更，请重新预览并核对", 409, "STOCK_IMPORT_STALE")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text(row, field, maximum, *, optional=False):
    value = row.get(field, "").strip()
    if (not value and not optional) or len(value) > maximum or any(ord(c) < 32 for c in value):
        invalid("照片字段无效：" + field)
    return value


def _parse(body, *, applying=False):
    if not isinstance(body, dict) or set(body) != SOURCE_FIELDS | (CONFIRM_FIELDS if applying else set()):
        invalid("照片导入参数无效")
    encoded, expected = body["source_base64"], body["source_sha256"]
    if (
        not isinstance(encoded, str)
        or len(encoded) > 350000
        or not isinstance(expected, str)
        or not re.fullmatch("[0-9a-f]{64}", expected)
    ):
        invalid("来源文件或SHA256无效")
    try:
        raw = base64.b64decode(encoded, validate=True)
        text = raw.decode("utf-8-sig")
    except (ValueError, UnicodeError, binascii.Error):
        invalid("来源必须是UTF-8 CSV文件")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ApiError("来源文件SHA256不匹配", 400, "STOCK_IMPORT_HASH_MISMATCH")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        fields = reader.fieldnames or []
        if len(set(fields)) != len(fields) or not REQUIRED <= set(fields) or set(fields) - REQUIRED - OPTIONAL:
            invalid("CSV列不完整、重复或包含未审核字段")
        evidence = list(reader)
    except csv.Error:
        invalid("CSV格式无效")
    if not 1 <= len(evidence) <= 500:
        invalid("CSV必须包含1至500行证据")
    ready, excluded, seen = [], [], set()
    for row in evidence:
        if None in row or any(value is None or len(value) > 1000 for value in row.values()):
            invalid("CSV行缺列、超列或字段过长")
        number = row["row"]
        if not re.fullmatch("[1-9][0-9]{0,5}", number) or number in seen:
            invalid("照片行号无效或重叠重复；每个原始行号仅保留一次")
        seen.add(number)
        _text(row, "source_photo", 120)
        status = row["review_status"]
        if status != "ready":
            if not re.fullmatch("needs_[a-z_]+", status):
                invalid("照片审核状态无效")
            excluded.append({"row": number, "review_status": status, "evidence": row})
            continue
        base = _text(row, "base_unit", 20)
        package = _text(row, "package_unit", 20)
        if base not in UNITS or package not in UNITS:
            invalid("已审核行必须明确基本单位及包装单位，未知单位不得导入")
        if any(
            field in row and not row[field].strip() for field in ("original_quantity", "original_unit", "input_unit")
        ):
            invalid("已审核行的原始数量和单位列不能留空")
        factor = stock_quantity(row["units_per_package"])
        mode = row.get("input_unit") or ("package" if row["package_quantity"] else "base")
        if mode not in {"base", "package"}:
            invalid("照片输入单位无效")
        original = row.get("original_quantity") or (
            row["package_quantity"] if mode == "package" else row["basic_quantity"]
        )
        quantity = stock_quantity(original, zero=True)
        unit = package if mode == "package" else base
        if row.get("original_unit") and row["original_unit"] != unit:
            invalid("照片原始单位与输入单位不一致")
        if mode == "package" and stock_quantity(row["package_quantity"], zero=True) != quantity:
            invalid("照片原始数量与包装数量不一致")
        target = stock_quantity(quantity * (factor if mode == "package" else Decimal(1)), zero=True)
        if stock_quantity(row["basic_quantity"], zero=True) != target:
            invalid("照片基本数量与精确换算结果不一致")
        ready.append(
            {
                "row": number,
                "name": _text(row, "name", 120),
                "category": _text(row, "category", 80),
                "base_unit": base,
                "package_unit": package,
                "units_per_package": f"{factor:.3f}",
                "package_spec": _text(row, "package_spec", 120, optional=True),
                "input_quantity": f"{quantity:.3f}",
                "input_unit": unit,
                "input_mode": mode,
                "target_quantity": f"{target:.3f}",
                "evidence": row,
            }
        )
    mapping = body["mapping"]
    if not isinstance(mapping, dict) or set(mapping) != {r["row"] for r in ready}:
        invalid("必须逐一确认全部已审核行的稳定库存ID或新建映射；未核对行不可映射")
    targets = set()
    for value in mapping.values():
        if not isinstance(value, dict):
            invalid("库存映射无效")
        if set(value) == {"create"} and value["create"] is True:
            continue
        if (
            set(value) != {"stock_item_id"}
            or not isinstance(value["stock_item_id"], str)
            or not re.fullmatch("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value["stock_item_id"])
        ):
            invalid("新建必须显式确认，已有库存仅允许稳定ID映射")
        if value["stock_item_id"] in targets:
            invalid("多行不得覆盖同一个库存主档")
        targets.add(value["stock_item_id"])
    return ready, excluded


def _receipt(source_hash):
    # AuditLog has no PeriodMixin; unlike movements/idempotency this lookup is global.
    return AuditLog.query.filter_by(
        action="stock.photo_import", entity_type="stock_source", entity_id=source_hash
    ).first()


def _preview(body, ready, excluded, *, lock=False):
    rows = []
    for row in ready:
        mapping = body["mapping"][row["row"]]
        before = None
        if "stock_item_id" in mapping:
            query = StockItem.query.filter_by(id=mapping["stock_item_id"]).populate_existing()
            master = (query.with_for_update() if lock else query).first()
            if (
                not master
                or not master.is_active
                or master.base_unit != row["base_unit"]
                or master.package_unit != row["package_unit"]
                or master.units_per_package != Decimal(row["units_per_package"])
            ):
                stale()
            before = stock_item_dict(master)
        delta = Decimal(row["target_quantity"]) - Decimal(before["stock_quantity"] if before else "0")
        rows.append({**row, "mapping": mapping, "before": before, "delta": f"{delta:.3f}"})
    result = {
        "source_sha256": body["source_sha256"],
        "period_id": current_period_id(),
        "mapping": body["mapping"],
        "rows": rows,
        "excluded": excluded,
        "summary": {
            "evidence_rows": len(ready) + len(excluded),
            "ready_rows": len(ready),
            "excluded_rows": len(excluded),
        },
    }
    return {**result, "preview_digest": digest(result)}


def preview_import(body):
    ready, excluded = _parse(body)
    receipt = _receipt(body["source_sha256"])
    if receipt:
        if receipt.details["preview"]["mapping"] != body["mapping"]:
            stale()
        return {**receipt.details["preview"], "already_applied_receipt_id": receipt.id}
    return _preview(body, ready, excluded)


def apply_import(body, employee):
    ready, excluded = _parse(body, applying=True)
    if (
        body["confirm"] is not True
        or not isinstance(body["preview_digest"], str)
        or not isinstance(body["period_id"], str)
    ):
        invalid("必须确认来源摘要、预览和经营期")
    original = _receipt(body["source_sha256"])
    if original:
        preview = original.details["preview"]
        if any(body[key] != preview[key] for key in ("mapping", "period_id", "preview_digest")):
            stale()
        return original.details["result"], True
    preview = _preview(body, ready, excluded, lock=True)
    if any(body[key] != preview[key] for key in ("period_id", "preview_digest")):
        stale()
    if not ready:
        invalid("没有已审核可导入的行")
    receipt_id, rows = new_uuid(), []
    for row in preview["rows"]:
        before = row["before"]
        if before:
            master = db.session.get(StockItem, before["id"])
        else:
            master = StockItem(
                **{key: row[key] for key in ("name", "category", "base_unit", "package_unit", "package_spec")},
                units_per_package=Decimal(row["units_per_package"]),
                stock_quantity=Decimal(0),
                low_stock_threshold=Decimal(0),
                is_active=True,
            )
            db.session.add(master)
            db.session.flush()
        delta = Decimal(row["delta"])
        movement = (
            change_balance(
                master,
                delta,
                employee,
                "photo_count",
                "照片盘点行" + row["row"],
                input_quantity=Decimal(row["input_quantity"]),
                input_unit=row["input_mode"],
                factor=Decimal(row["units_per_package"]) if row["input_mode"] == "package" else Decimal(1),
                reference_type="stock_photo_import",
                reference_id=receipt_id,
            )
            if delta
            else None
        )
        rows.append(
            {
                "row": row["row"],
                "before": before,
                "after": stock_item_dict(master),
                "movement_id": movement.id if movement else None,
            }
        )
    result = {
        "receipt_id": receipt_id,
        "source_sha256": body["source_sha256"],
        "period_id": preview["period_id"],
        "summary": preview["summary"],
        "excluded": excluded,
        "rows": rows,
    }
    write_audit(
        "stock.photo_import",
        "stock_source",
        body["source_sha256"],
        {"preview": preview, "result": result},
        record_id=receipt_id,
    )
    return result, False
