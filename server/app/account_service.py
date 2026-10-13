"""Password changes authenticate only the current, locked login principal."""
from .api.errors import ApiError
from .audit_service import write_audit
from .auth_service import hash_password, verify_sensitive_password
from .extensions import db


def change_own_password(employee, body):
    fields = {'old_password', 'new_password', 'confirm_password'}
    if (not isinstance(body, dict) or set(body) != fields
            or any(not isinstance(body[key], str) for key in fields)):
        raise ApiError('请填写旧密码、新密码和确认密码，不接受其他账号或字段', 400, 'INVALID_PASSWORD_FIELDS')
    verify_sensitive_password(employee, body['old_password'])
    if body['new_password'] != body['confirm_password']:
        raise ApiError('两次新密码不一致', 400, 'PASSWORD_CONFIRM_MISMATCH')
    if body['new_password'] == body['old_password']:
        raise ApiError('新密码不能与旧密码相同', 400, 'PASSWORD_UNCHANGED')
    employee.password_hash = hash_password(body['new_password'])
    employee.session_version += 1
    write_audit('account.password_change', 'employee', employee.id, {'sessions_revoked': True})
    db.session.commit()
    from .access_policy import revalidate_sockets
    revalidate_sockets()

