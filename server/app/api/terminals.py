from flask import Blueprint, request

from ..access_policy import revalidate_sockets
from ..audit_service import write_audit
from ..auth_service import current_employee, has_permission, require_permission
from ..extensions import db
from ..models import Terminal
from ..serializers import terminal_dict
from .errors import ApiError, success

bp = Blueprint("terminals", __name__, url_prefix="/terminals")


@bp.post("/register")
def register_terminal():
    body = request.get_json(silent=True) or {}
    code = str(body.get("code", "")).strip()
    name = str(body.get("name", "")).strip() or code
    if not code:
        raise ApiError("终端编码不能为空")
    terminal = Terminal.query.filter_by(code=code).first()
    if terminal:
        if not terminal.is_active:
            raise ApiError("终端已停用，请联系管理员", 403, "TERMINAL_DISABLED")
    else:
        terminal = Terminal(code=code, name=name)
        db.session.add(terminal)
    db.session.commit()
    return success(terminal_dict(terminal), "终端注册成功", 201)


@bp.get("")
@require_permission("settings:read")
def list_terminals():
    return success([terminal_dict(row) for row in Terminal.query.order_by(Terminal.name).all()])


@bp.patch("/<terminal_id>")
@require_permission("settings:read")
def update_terminal(terminal_id):
    terminal = db.get_or_404(Terminal, terminal_id)
    body = request.get_json(silent=True) or {}
    employee = current_employee()
    if not has_permission(employee, "*") and any(key in body for key in ("name", "is_active")):
        raise ApiError("修改终端身份或停用终端需要管理员权限", 403, "FORBIDDEN")
    before = terminal_dict(terminal)
    if "name" in body:
        terminal.name = str(body["name"]).strip()
    if "printer_name" in body:
        from flask_jwt_extended import get_jwt

        if not has_permission(employee, "*") and get_jwt().get("terminal_id") != terminal.id:
            raise ApiError("只能修改当前终端的打印设置", 403, "FORBIDDEN")
        terminal.printer_name = str(body["printer_name"]).strip() or None
    if "is_active" in body:
        terminal.is_active = bool(body["is_active"])
    write_audit(
        "terminal.update",
        "terminal",
        terminal.id,
        {"before": before, "after": terminal_dict(terminal)},
    )
    db.session.commit()
    revalidate_sockets()
    return success(terminal_dict(terminal))
