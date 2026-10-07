from decimal import Decimal

from flask import Blueprint, request

from ..access_policy import emit_business_event
from ..audit_service import write_audit
from ..auth_service import require_permission
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..models import SystemSetting
from ..pricing_service import reprice_open_compensation_items
from ..validation import decimal_value
from .errors import ApiError, success

bp = Blueprint("settings", __name__, url_prefix="/settings")


def setting_dict(row):
    return {"id": row.id, "key": row.key, "value": row.value, "description": row.description}


@bp.get("")
@require_permission("settings:read")
def list_settings():
    return success(
        [
            setting_dict(row)
            for row in SystemSetting.query.order_by(SystemSetting.key).all()
            if row.key != "force_clear_password"
        ]
    )


@bp.put("/<key>")
@require_permission("*")
@serialized_financial_write
def update_setting(key):
    if key == "force_clear_password":
        raise ApiError("共享操作密码已停用，清空账单请验证本人登录密码", 400, "DEPRECATED_SETTING")
    body = request.get_json(silent=True) or {}
    if "value" not in body:
        raise ApiError("缺少 value")
    value = body["value"]
    if key == "lost_wristband_fee":
        fee = decimal_value(value, "挂失赔偿金额")
        value = f"{fee:.2f}"
    row = SystemSetting.query.filter_by(key=key).first()
    before = row.value if row else None
    if row is None:
        row = SystemSetting(key=key, value=value, description=body.get("description"))
        db.session.add(row)
    else:
        row.value = value
        if "description" in body:
            row.description = body["description"]
    repriced = (
        reprice_open_compensation_items(Decimal(value))
        if key == "lost_wristband_fee"
        else {"item_count": 0, "visit_ids": []}
    )
    write_audit(
        "setting.update",
        "setting",
        key,
        {"before": before, "after": row.value, "repriced_open_bills": repriced},
    )
    db.session.commit()
    if repriced["visit_ids"]:
        emit_business_event("visit.changed", {"reason": "lost_fee_changed", **repriced})
    return success(setting_dict(row))
