import hmac
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
)

from ..access_policy import (
    effective_permissions,
    policy_claims,
    policy_enforced,
    revalidate_sockets,
    session_permissions,
)
from ..audit_service import write_audit
from ..auth_service import current_employee, hash_password, verify_password
from ..business_period import business_state_data
from ..extensions import db
from ..models import Employee, RevokedSession, Terminal, new_uuid
from ..serializers import employee_dict, terminal_dict
from .errors import ApiError, success

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _seconds(duration):
    return int(duration.total_seconds()) if isinstance(duration, timedelta) else int(duration)


def _access_expiry(deadline):
    configured = _seconds(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"])
    remaining = deadline - int(datetime.now(timezone.utc).timestamp())
    return timedelta(seconds=max(1, min(configured, remaining)))


def _locked(employee: Employee) -> bool:
    if not employee.locked_until:
        return False
    locked_until = employee.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > datetime.now(timezone.utc)


@bp.post("/bootstrap")
def bootstrap():
    if Employee.query.count() > 0:
        raise ApiError("系统已经初始化", 409, "ALREADY_BOOTSTRAPPED")
    body = request.get_json(silent=True) or {}
    expected_token = str(current_app.config.get("BOOTSTRAP_TOKEN", ""))
    provided_token = str(body.get("bootstrap_token", ""))
    if expected_token and not hmac.compare_digest(provided_token, expected_token):
        raise ApiError("首次初始化口令错误", 403, "INVALID_BOOTSTRAP_TOKEN")
    username = str(body.get("username", "admin")).strip()
    display_name = str(body.get("display_name", "系统管理员")).strip()
    password = str(body.get("password", ""))
    if not username or not display_name:
        raise ApiError("用户名和姓名不能为空")

    employee = Employee(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        role="admin",
    )
    db.session.add(employee)
    db.session.flush()
    write_audit(
        "system.bootstrap",
        "employee",
        employee.id,
        {"username": username, "display_name": display_name},
        employee_id=employee.id,
    )
    db.session.commit()
    return success(employee_dict(employee), "初始化完成", 201)


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    terminal_code = str(body.get("terminal_code", "")).strip()
    employee = Employee.query.filter_by(username=username).first()
    if employee:
        g.audit_employee_id = employee.id
    terminal_for_audit = Terminal.query.filter_by(code=terminal_code).first()
    if terminal_for_audit:
        g.audit_terminal_id = terminal_for_audit.id
    if not employee or not employee.is_active or employee.deleted_at:
        raise ApiError("用户名或密码错误", 401, "INVALID_CREDENTIALS")
    if _locked(employee):
        raise ApiError("账号已锁定，请稍后重试", 423, "ACCOUNT_LOCKED")
    if not verify_password(employee.password_hash, password):
        employee.failed_login_attempts += 1
        if employee.failed_login_attempts >= 5:
            employee.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            employee.failed_login_attempts = 0
        db.session.commit()
        raise ApiError("用户名或密码错误", 401, "INVALID_CREDENTIALS")

    terminal = Terminal.query.filter_by(code=terminal_code, is_active=True).first()
    if not terminal:
        raise ApiError("终端未注册或已停用", 403, "TERMINAL_INVALID")

    channel = body.get('client_channel')
    if not policy_enforced() and channel is None:
        channel = 'mobile' if terminal.code.startswith('MOBILE-') else 'desktop'
    permissions = session_permissions(employee, channel)
    if policy_enforced() and channel == 'mobile':
        from ..employee_access import session_ui
        if not session_ui(employee, channel, permissions)['ui_pages']:
            raise ApiError('该账号当前没有可用的手机业务入口', 403, 'CHANNEL_FORBIDDEN')

    employee.failed_login_attempts = 0
    employee.locked_until = None
    employee.last_login_at = datetime.now(timezone.utc)
    terminal.last_seen_at = datetime.now(timezone.utc)
    refresh_expires = timedelta(seconds=_seconds(current_app.config["JWT_REFRESH_TOKEN_EXPIRES"]))
    if channel == 'mobile':
        refresh_expires = timedelta(hours=8) if employee.role == "admin" else timedelta(days=7)
    deadline = int(datetime.now(timezone.utc).timestamp()) + _seconds(refresh_expires)
    claims = {
        "role": employee.role,
        "terminal_id": terminal.id,
        "session_version": employee.session_version,
        "session_id": new_uuid(),
        "session_expires_at": deadline,
        **policy_claims(employee, channel),
    }
    access_token = create_access_token(
        identity=employee.id, additional_claims=claims, expires_delta=_access_expiry(deadline)
    )
    refresh_token = create_refresh_token(
        identity=employee.id,
        additional_claims=claims,
        expires_delta=refresh_expires,
    )
    g.audit_session_id = claims["session_id"]
    g.audit_authenticated = True
    write_audit(
        "auth.login",
        "employee",
        employee.id,
        {"terminal_code": terminal.code},
        employee_id=employee.id,
        terminal_id=terminal.id,
    )
    db.session.commit()
    return success(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "employee": employee_dict(employee, channel),
            "terminal": terminal_dict(terminal),
            "business_state": business_state_data(employee, channel),
            "permissions": claims['permission_scope'],
        },
        "登录成功",
    )


@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    employee = current_employee()
    from flask_jwt_extended import get_jwt

    old_claims = get_jwt()
    claims = {
        "role": employee.role,
        "terminal_id": old_claims.get("terminal_id"),
        "session_version": employee.session_version,
        "session_id": old_claims.get("session_id") or new_uuid(),
        "session_expires_at": old_claims.get("session_expires_at", old_claims["exp"]),
        **policy_claims(employee, old_claims.get('client_channel'), previous=old_claims),
    }
    return success(
        {
            "access_token": create_access_token(
                identity=employee.id,
                additional_claims=claims,
                expires_delta=_access_expiry(claims["session_expires_at"]),
            ),
            'business_state': business_state_data(employee),
            'permissions': sorted(effective_permissions(employee, claims)),
            'employee': employee_dict(employee, old_claims.get('client_channel')),
        }
    )


@bp.get("/me")
@jwt_required()
def me():
    employee = current_employee()
    return success(employee_dict(employee))


@bp.post("/logout")
@jwt_required()
def logout():
    employee = current_employee()
    from flask_jwt_extended import get_jwt

    session_id = get_jwt().get("session_id")
    if session_id:
        db.session.add(RevokedSession(id=session_id, employee_id=employee.id))
    else:
        employee.session_version += 1
    write_audit("auth.logout", "employee", employee.id, {})
    db.session.commit()
    revalidate_sockets()
    return success(message="已退出登录")
