from flask import Blueprint, request

from ..access_policy import active_policy, policy_enforced, revalidate_sockets
from ..audit_service import write_audit
from ..auth_service import current_employee, hash_password, require_permission
from ..extensions import db
from ..employee_access import DEFAULT_CHANNELS, is_protected_employee, validate_employee_channels
from ..models import Employee, utcnow
from ..serializers import employee_dict
from .errors import ApiError, success

bp = Blueprint("employees", __name__, url_prefix="/employees")
VALID_ROLES = {
    "male_scrubber",
    "female_scrubber",
    "floor_attendant",
    "cashier",
    "inventory",
    "manager",
    "admin",
}


@bp.get("")
@require_permission("employee:read")
def list_employees():
    deleted = request.args.get('deleted', 'exclude')
    if deleted not in {'exclude', 'only'}:
        raise ApiError('删除状态筛选无效')
    query = Employee.query.filter(Employee.deleted_at.is_not(None) if deleted == 'only' else Employee.deleted_at.is_(None))
    return success([employee_dict(row) for row in query.order_by(Employee.created_at).all()])


def _body():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise ApiError('员工资料必须是对象')
    if any(key not in {'username', 'display_name', 'role', 'password', 'is_active', 'allowed_channels', 'unlock'} for key in body):
        raise ApiError('不允许直接填写权限或其他安全字段', 400, 'INVALID_EMPLOYEE_FIELDS')
    for key in ('is_active', 'unlock'):
        if key in body and type(body[key]) is not bool:
            raise ApiError('启用和解锁状态必须为布尔值')
    return body


def _ordinary_channels(role, supplied):
    if not policy_enforced() and role == 'admin':
        return []  # Existing isolated legacy fixtures; never a production grant.
    return validate_employee_channels(role, supplied)


@bp.post("")
@require_permission("*")
def create_employee():
    body = _body()
    username = str(body.get("username", "")).strip()
    display_name = str(body.get("display_name", "")).strip()
    role = str(body.get("role", "cashier"))
    if not username or not display_name or len(username) > 50 or len(display_name) > 80:
        raise ApiError("用户名和姓名不能为空")
    if role not in VALID_ROLES:
        raise ApiError("角色无效")
    if Employee.query.filter_by(username=username).first():
        raise ApiError("用户名已存在", 409, "USERNAME_EXISTS")
    if policy_enforced() and role == 'admin':
        raise ApiError('最高管理员须通过既有账号UUID策略核对，不可在此新建授权', 403, 'PERMISSION_DENIED')
    channels = _ordinary_channels(role, body.get('allowed_channels', [] if policy_enforced() else list(DEFAULT_CHANNELS.get(role, ()))))
    is_active = body.get('is_active', True)
    if policy_enforced() and is_active and not channels:
        raise ApiError('请先选择岗位允许使用的入口，再启用账号', 403, 'PERMISSION_DENIED')
    employee = Employee(
        username=username,
        display_name=display_name,
        role=role,
        password_hash=hash_password(str(body.get("password", ""))),
        is_active=is_active,
        allowed_channels=channels,
    )
    db.session.add(employee)
    db.session.flush()
    write_audit("employee.create", "employee", employee.id, employee_dict(employee))
    db.session.commit()
    return success(employee_dict(employee), "员工创建成功", 201)


@bp.patch("/<employee_id>")
@require_permission("*")
def update_employee(employee_id):
    employee = Employee.query.populate_existing().filter_by(id=employee_id).with_for_update().first_or_404()
    if employee.deleted_at:
        raise ApiError('该账号已删除，不能通过普通编辑恢复', 409, 'EMPLOYEE_DELETED')
    body = _body()
    if 'username' in body and body['username'] != employee.username:
        raise ApiError('历史责任账号不能更改用户名')
    protected = is_protected_employee(employee)
    new_role = body.get('role', employee.role)
    if new_role not in VALID_ROLES:
        raise ApiError('角色无效')
    if protected and ('allowed_channels' in body or ('role' in body and new_role != employee.role)
                      or ('is_active' in body and not body['is_active'])):
        raise ApiError('此账号是受保护的既有管理员，入口和身份须使用策略维护', 403, 'PROTECTED_ACCOUNT')
    if policy_enforced():
        policy = active_policy()
        if (employee.id == policy.owner_id and body.get('password')
                and current_employee().id != policy.owner_id):
            raise ApiError('仅店主本人可以修改重置账号的密码', 403, 'OWNER_REQUIRED')
        if not protected and new_role == 'admin':
            raise ApiError('不能通过普通角色编辑授予最高管理员', 403, 'PERMISSION_DENIED')
    channels = employee.allowed_channels
    if not protected:
        channels = _ordinary_channels(new_role, body.get('allowed_channels', channels))
        if policy_enforced() and body.get('is_active', employee.is_active) and not channels:
            raise ApiError('请先选择该账号允许使用的入口，再启用账号', 403, 'PERMISSION_DENIED')
    before = employee_dict(employee)
    security_changed = False
    if "display_name" in body:
        name = str(body['display_name']).strip()
        if not name or len(name) > 80:
            raise ApiError('员工姓名不能为空且不能超过80字')
        employee.display_name = name
    if "role" in body:
        if body["role"] not in VALID_ROLES:
            raise ApiError("角色无效")
        if body["role"] != employee.role:
            employee.role = body["role"]
            security_changed = True
    if "is_active" in body:
        is_active = body["is_active"]
        if is_active != employee.is_active:
            employee.is_active = is_active
            security_changed = True
    if body.get("password"):
        employee.password_hash = hash_password(str(body["password"]))
        security_changed = True
    if channels != employee.allowed_channels:
        employee.allowed_channels = channels
        security_changed = True
    if body.get("unlock"):
        employee.failed_login_attempts = 0
        employee.locked_until = None
        security_changed = True
    if security_changed:
        employee.session_version += 1
    write_audit(
        "employee.update",
        "employee",
        employee.id,
        {"before": before, "after": employee_dict(employee)},
    )
    db.session.commit()
    revalidate_sockets()
    return success(employee_dict(employee))


@bp.delete('/<employee_id>')
@require_permission('*')
def delete_employee(employee_id):
    employee = Employee.query.populate_existing().filter_by(id=employee_id).with_for_update().first_or_404()
    if employee.id == current_employee().id or is_protected_employee(employee):
        raise ApiError('不能删除自己或受保护的既有管理员', 403, 'PROTECTED_ACCOUNT')
    if employee.deleted_at:
        return success(employee_dict(employee), '账号已删除')
    before = employee_dict(employee)
    employee.deleted_at = utcnow()
    employee.is_active = False
    employee.allowed_channels = []
    employee.session_version += 1
    write_audit('employee.delete', 'employee', employee.id, {'before': before, 'after': employee_dict(employee)})
    db.session.commit()
    revalidate_sockets()
    return success(employee_dict(employee), '账号已删除，历史操作记录保留')
