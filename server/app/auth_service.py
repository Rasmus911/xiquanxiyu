from datetime import datetime, timezone
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import g
from flask_jwt_extended import get_jwt, verify_jwt_in_request

from .api.errors import ApiError
from .extensions import db
from .models import Employee, RevokedSession, Terminal

password_hasher = PasswordHasher()

ROLE_PERMISSIONS = {
    "male_scrubber": {"visit:read", "visit:order", "mobile:order"},
    "female_scrubber": {"visit:read", "visit:order", "mobile:order"},
    "floor_attendant": {"visit:read", "visit:order", "mobile:order"},
    "cashier": {
        "report:read",
        "visit:clear", "member:delete", "catalog:delete",
        "visit:read",
        "visit:write",
        "visit:order",
        "visit:package",
        "checkout:write",
        "member:read",
        "member:write",
        "print:write",
        "inventory:read", "inventory:write", "catalog:read", "catalog:write", "catalog:layout",
    },
    "inventory": {"report:read", "visit:read", "visit:write", "visit:order", "mobile:order", "visit:package",
        "visit:clear", "member:delete", "catalog:delete",
        "checkout:write", "member:read", "member:write", "print:write",
        "inventory:read", "inventory:write", "catalog:read", "catalog:write", "catalog:layout"},
    "manager": {
        "visit:clear", "member:delete", "catalog:delete",
        "visit:read",
        "visit:write",
        "visit:order",
        "visit:package",
        "checkout:write",
        "checkout:refund",
        "member:read",
        "member:write",
        "inventory:read",
        "inventory:write",
        "catalog:read",
        "catalog:write",
        "report:read",
        "audit:read",
        "employee:read",
        "settings:read",
        "print:write",
    },
    "admin": {"*"},
}


def hash_password(password: str) -> str:
    if not 8 <= len(password) <= 128:
        raise ApiError("密码需要 8–128 位，建议使用 12 位以上独立密码", code="WEAK_PASSWORD")
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    if len(password) > 128:
        return False
    try:
        return password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def session_expired(claims) -> bool:
    deadline = claims.get("session_expires_at")
    if deadline is None:
        return False  # Legacy sessions are revoked by the upgrade migration.
    try:
        return int(deadline) <= int(datetime.now(timezone.utc).timestamp())
    except (TypeError, ValueError, OverflowError):
        return True


def current_employee() -> Employee:
    employee = employee_for_claims(get_jwt())
    from .access_policy import validate_period_header

    validate_period_header()
    from .business_period import bind_authenticated_read_period

    bind_authenticated_read_period(get_jwt())
    g.audit_employee_id = employee.id
    g.audit_terminal_id = get_jwt().get('terminal_id')
    g.audit_authenticated = True
    return employee


def employee_for_claims(claims) -> Employee:
    """Shared HTTP/socket validation; callers verify JWT signature/type/expiry."""
    employee = db.session.get(Employee, claims.get('sub'), populate_existing=True)
    if not employee or not employee.is_active or employee.deleted_at:
        raise ApiError("账号不可用，请重新登录", 401, "ACCOUNT_DISABLED")
    locked_until = employee.locked_until
    if locked_until and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if locked_until and locked_until > datetime.now(timezone.utc):
        raise ApiError("账号已锁定", 423, "ACCOUNT_LOCKED")
    if session_expired(claims):
        raise ApiError("本次登录已到期，请重新登录", 401, "SESSION_EXPIRED")
    if claims.get("session_id") and db.session.get(RevokedSession, claims["session_id"]):
        raise ApiError("已退出该会话，请重新登录", 401, "SESSION_REVOKED")
    if int(claims.get("session_version", 0)) != employee.session_version:
        raise ApiError("登录状态已失效，请重新登录", 401, "SESSION_REVOKED")
    terminal = db.session.get(Terminal, claims.get("terminal_id"), populate_existing=True)
    if not terminal or not terminal.is_active:
        raise ApiError("终端已停用，请联系管理员", 401, "TERMINAL_DISABLED")
    from .access_policy import validate_session_policy

    validate_session_policy(employee, claims)
    return employee


def verify_sensitive_password(employee, password):
    if not verify_password(employee.password_hash, str(password or "")):
        employee.failed_login_attempts += 1
        if employee.failed_login_attempts >= 5:
            from datetime import timedelta

            employee.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            employee.failed_login_attempts = 0
        db.session.commit()
        raise ApiError("本人登录密码错误", 403, "REAUTH_FAILED")
    employee.failed_login_attempts = 0


def has_permission(employee: Employee, permission: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(employee.role, set())
    if '*' not in permissions and permission not in permissions:
        return False
    from .access_policy import effective_permissions, is_owner, policy_enforced

    if not policy_enforced():
        return True
    if permission in {'business:reset', 'business:archive'} and not is_owner(employee):
        return False
    scope = effective_permissions(employee, get_jwt())
    return '*' in scope or permission in scope


def require_permission(permission: str):
    return require_any_permission(permission)


def require_any_permission(*permissions: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            employee = current_employee()
            if not any(has_permission(employee, permission) for permission in permissions):
                code = 'OWNER_REQUIRED' if set(permissions) <= {'business:reset', 'business:archive'} else 'PERMISSION_DENIED'
                raise ApiError("没有执行此操作的权限", 403, code)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
