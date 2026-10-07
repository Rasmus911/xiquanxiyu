"""UUID-bound account and channel policy. Names and terminal codes never grant scope."""
import json
import threading
from uuid import UUID

import click
from flask import current_app, request
from flask_jwt_extended import decode_token, get_jwt
from flask_socketio import join_room
from sqlalchemy import update

from .api.errors import ApiError
from .extensions import db, socketio
from .models import AccessPolicyModel, BusinessStateModel, Employee

MOBILE_SCOPE = {'mobile:order', 'visit:package', 'report:read', 'inventory:read', 'inventory:write',
                'catalog:read', 'catalog:write', 'catalog:layout'}
OWNER_SCOPE = {'business:reset', 'business:archive'}


def policy_enforced():
    # An explicit legacy fixture mode is permitted; production cannot select it.
    return current_app.config.get('PRODUCTION', False) or not current_app.config.get(
        'ACCESS_POLICY_LEGACY_COMPAT', False)


def _binding_ids(owner_id, mobile_ids):
    try:
        if not isinstance(mobile_ids, list) or len(mobile_ids) != 2:
            raise ValueError
        ids = [owner_id, *mobile_ids]
        if any(not isinstance(value, str) or str(UUID(value)) != value for value in ids):
            raise ValueError
        if len(set(ids)) != 3:
            raise ValueError
        return ids
    except (ValueError, TypeError, AttributeError):
        raise ApiError('必须绑定三个不同的既有账号 UUID', 503,
                       'ACCESS_POLICY_NOT_CONFIGURED') from None


def _administrator_ids(owner_id, administrator_ids):
    try:
        if not isinstance(administrator_ids, list):
            raise ValueError
        if (owner_id in administrator_ids or len(set(administrator_ids)) != len(administrator_ids)
                or any(not isinstance(value, str) or str(UUID(value)) != value for value in administrator_ids)):
            raise ValueError
        return administrator_ids
    except (ValueError, TypeError, AttributeError):
        raise ApiError('高级管理员必须使用不同的既有账号 UUID，不重复店主', 503,
                       'ACCESS_POLICY_NOT_CONFIGURED') from None


def active_policy():
    state = BusinessStateModel.query.populate_existing().filter_by(id=1).first()
    policies = AccessPolicyModel.query.populate_existing().filter_by(is_active=True).all()
    if not state or len(policies) != 1 or policies[0].policy_version != state.policy_version:
        raise ApiError('入口权限策略尚未核对激活', 503, 'ACCESS_POLICY_NOT_CONFIGURED')
    policy = policies[0]
    ids = set(_binding_ids(policy.owner_id, policy.mobile_employee_ids))
    ids.update(_administrator_ids(policy.owner_id, policy.administrator_employee_ids))
    employees = Employee.query.populate_existing().filter(Employee.id.in_(ids)).all()
    if (len(employees) != len(ids) or state.policy_version < 1
            or not any(row.id == policy.owner_id and row.is_active for row in employees)):
        raise ApiError('入口权限策略绑定无效', 503, 'ACCESS_POLICY_NOT_CONFIGURED')
    return policy


def is_owner(employee):
    if not policy_enforced() or not employee or not employee.is_active:
        return False
    return employee.id == active_policy().owner_id


def session_permissions(employee, channel):
    from .auth_service import ROLE_PERMISSIONS

    role_scope = ROLE_PERMISSIONS.get(employee.role, set())
    if not policy_enforced():
        return set(role_scope) & MOBILE_SCOPE if channel == 'mobile' and '*' not in role_scope else set(role_scope)
    policy = active_policy()
    if channel == 'mobile' and employee.role != 'admin':
        from .employee_access import DEFAULT_CHANNELS
        if 'mobile' not in DEFAULT_CHANNELS.get(employee.role, ()):
            raise ApiError('该岗位不允许使用手机入口',403,'CHANNEL_FORBIDDEN')
    if (not employee.is_active or employee.deleted_at or not isinstance(channel, str)
            or channel not in {'desktop', 'web', 'mobile'}):
        raise ApiError('该账号不允许使用此入口', 403, 'CHANNEL_FORBIDDEN')
    owner = employee.id == policy.owner_id
    administrator = employee.id in policy.administrator_employee_ids and employee.role == 'admin'
    mobile_binding = employee.id in policy.mobile_employee_ids
    if not owner and not administrator and not mobile_binding:
        from .employee_access import validate_employee_channels

        try:
            channels = validate_employee_channels(employee.role, employee.allowed_channels)
        except ApiError:
            raise ApiError('账号入口授权无效，请联系管理员', 403, 'CHANNEL_FORBIDDEN') from None
        if channel not in channels:
            raise ApiError('该账号尚未获准使用此入口', 403, 'CHANNEL_FORBIDDEN')
        return set(role_scope) & MOBILE_SCOPE if channel == 'mobile' else set(role_scope)
    if channel in {'desktop', 'web'}:
        if not owner and not administrator:
            raise ApiError('该账号未绑定电脑管理入口', 403, 'CHANNEL_FORBIDDEN')
        allowed = {'*'} | (OWNER_SCOPE if owner else set())
    else:
        if not owner and not administrator and not mobile_binding:
            raise ApiError('该账号不在手机入口名单中', 403, 'CHANNEL_FORBIDDEN')
        allowed = MOBILE_SCOPE | (OWNER_SCOPE if owner else set())
    return allowed if '*' in role_scope else allowed & role_scope


def _intersect_scopes(left, right):
    if '*' in left:
        return set(right)
    if '*' in right:
        return set(left)
    return set(left) & set(right)


def validate_session_policy(employee, claims):
    if not policy_enforced():
        return
    policy = active_policy()
    required = {'client_channel', 'permission_scope', 'policy_version', 'business_period_id'}
    scope = claims.get('permission_scope')
    if (not required <= claims.keys() or not isinstance(scope, list)
            or any(not isinstance(item, str) for item in scope)
            or type(claims['policy_version']) is not int
            or claims['policy_version'] != policy.policy_version):
        raise ApiError('入口授权已失效，请重新登录', 401, 'SESSION_REVOKED')
    state = BusinessStateModel.query.populate_existing().filter_by(id=1).one()
    if claims['business_period_id'] != state.period_id:
        raise ApiError('经营期已变更，请重新登录', 409, 'BUSINESS_PERIOD_CHANGED')
    session_permissions(employee, claims['client_channel'])
    if claims['client_channel'] == 'mobile' and '*' in scope:
        raise ApiError('手机入口授权范围无效', 403, 'CHANNEL_FORBIDDEN')


def validate_period_header():
    if not policy_enforced():
        return
    claims = get_jwt()
    supplied = request.headers.get('X-Business-Period')
    # Refresh/me/logout are authentication operations, not business operations.
    if (not request.path.startswith('/api/auth/') or supplied is not None):
        if supplied != claims.get('business_period_id'):
            raise ApiError('经营期凭据缺失或已变更，请重新登录', 409, 'BUSINESS_PERIOD_CHANGED')


def effective_permissions(employee, claims):
    allowed = session_permissions(employee, claims.get('client_channel'))
    if not policy_enforced():
        return allowed
    return _intersect_scopes(allowed, claims.get('permission_scope', []))


def policy_claims(employee, channel, previous=None):
    from .business_period import ensure_business_state

    state = ensure_business_state(db.session)
    permissions = (effective_permissions(employee, previous) if previous is not None
                   else session_permissions(employee, channel))
    return {'client_channel': channel, 'permission_scope': sorted(permissions),
            'policy_version': state.policy_version, 'business_period_id': state.period_id}


def activate_policy(owner_id: str, mobile_ids: list[str], administrator_ids=None) -> dict:
    """Maintenance CLI transaction; validate all bindings before touching employees."""
    administrator_ids = _administrator_ids(owner_id, [] if administrator_ids is None else administrator_ids)
    ids = set(_binding_ids(owner_id, mobile_ids)) | set(administrator_ids)
    try:
        from .business_barrier import shared_barrier
        shared_barrier(db.session.connection())
        state = BusinessStateModel.query.populate_existing().with_for_update().filter_by(id=1).one()
        employees = Employee.query.populate_existing().with_for_update().order_by(Employee.id).all()
        selected = [row for row in employees if row.id in ids]
        if len(selected) != len(ids) or any(not row.is_active for row in selected):
            raise ApiError('请先核对所有绑定账号的既有且启用 UUID', 503, 'ACCESS_POLICY_NOT_CONFIGURED')
        version = state.policy_version + 1
        # PostgreSQL's row lock serializes activations. The CAS also rejects a
        # concurrent stale SQLite activation without a partial employee change.
        result = db.session.execute(update(BusinessStateModel).where(
            BusinessStateModel.id == 1, BusinessStateModel.policy_version == version - 1
        ).values(policy_version=version))
        if result.rowcount != 1:
            raise ApiError('权限策略已改变，请重新核对', 409, 'SESSION_REVOKED')
        for policy in AccessPolicyModel.query.filter_by(is_active=True).all():
            policy.is_active = False
        db.session.add(AccessPolicyModel(owner_id=owner_id, mobile_employee_ids=list(mobile_ids),
                                        administrator_employee_ids=list(administrator_ids),
                                        policy_version=version, is_active=True))
        for employee in employees:
            employee.session_version += 1
            if employee.id in ids:
                employee.role = 'admin'
                employee.mobile_full_access = True
        from .audit_service import write_audit

        write_audit('access_policy.activate', 'access_policy', str(version),
                    {'owner_id': owner_id, 'mobile_ids': mobile_ids, 'administrator_ids': administrator_ids,
                     'policy_version': version},
                    employee_id=owner_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    invalidate_sockets({'policy_version': version}, event='access_policy.changed')
    return {'owner_id': owner_id, 'mobile_ids': mobile_ids, 'administrator_ids': administrator_ids,
            'policy_version': version}


# Only these payload families are emitted by the application. Unknown events
# fail closed; new event types must choose their authorized audience explicitly.
EVENT_PERMISSIONS = {
    'visit.changed': {'visit:read', 'mobile:order'},
    'wristbands.changed': {'visit:read', 'mobile:order'},
    'catalog.changed': {'visit:read', 'mobile:order', 'inventory:read'},
    'inventory.changed': {'inventory:read'},
    'member.changed': {'member:read'},
    'checkout.completed': {'checkout:write'},
    'checkout.refunded': {'checkout:write'},
}


def _socket_registry():
    return current_app.extensions['access_policy_sockets']


def _room(claims, event):
    return (f"business:{claims.get('business_period_id')}:{claims.get('policy_version')}:"
            f"{claims.get('client_channel')}:{event}")


def _socket_identity(token):
    from .auth_service import employee_for_claims

    claims = decode_token(token)
    if claims.get('type') != 'access':
        raise ApiError('请使用访问凭据连接', 401, 'SESSION_REVOKED')
    return claims, employee_for_claims(claims)


def revalidate_sockets():
    """Read committed policy and session state before emission and on idle sweeps."""
    registry = _socket_registry()
    with registry['lock']:
        for sid, connection in list(registry['clients'].items()):
            try:
                claims, employee = _socket_identity(connection['token'])
                permissions = effective_permissions(employee, claims)
                for event, required in EVENT_PERMISSIONS.items():
                    room = _room(claims, event)
                    if '*' in permissions or permissions & required:
                        socketio.server.enter_room(sid, room, namespace='/')
                    else:
                        socketio.server.leave_room(sid, room, namespace='/')
            except Exception:
                socketio.emit('session.invalidated', {'reason': 'SESSION_REVOKED'}, to=sid)
                socketio.server.disconnect(sid, namespace='/')
                registry['clients'].pop(sid, None)


def invalidate_sockets(data, event='session.invalidated'):
    """After a committed policy/reset change, notify then remove local sockets."""
    registry = _socket_registry()
    with registry['lock']:
        for sid in list(registry['clients']):
            socketio.emit(event, data, to=sid)
            socketio.server.disconnect(sid, namespace='/')
            registry['clients'].pop(sid, None)


def emit_business_event(event, data):
    if event not in EVENT_PERMISSIONS:
        raise ValueError(f'No authorized audience configured for {event}')
    revalidate_sockets()
    registry = _socket_registry()
    with registry['lock']:
        rooms = {_room(row['claims'], event) for row in registry['clients'].values()}
        for room in rooms:
            socketio.emit(event, data, to=room)


def _watch_sockets(app):
    # CLI activation is a separate maintenance process. Its database commit is
    # observed even while sockets are idle. This is not a multi-API-worker bus.
    registry = app.extensions['access_policy_sockets']
    try:
        while True:
            socketio.sleep(app.config['SOCKETIO_POLICY_POLL_SECONDS'])
            with registry['lock']:
                if not registry['clients']:
                    registry['watching'] = False
                    return
            with app.app_context():
                revalidate_sockets()
    finally:
        with registry['lock']:
            registry['watching'] = False


def register_policy_sockets(app):
    registry = {'clients': {}, 'lock': threading.RLock(), 'watching': False}
    app.extensions['access_policy_sockets'] = registry

    @socketio.on('connect')
    def connect(auth):
        try:
            token = auth.get('token') if isinstance(auth, dict) else None
            claims, employee = _socket_identity(token)
            permissions = effective_permissions(employee, claims)
            with registry['lock']:
                registry['clients'][request.sid] = {'token': token, 'claims': claims}
                for event, required in EVENT_PERMISSIONS.items():
                    if '*' in permissions or permissions & required:
                        join_room(_room(claims, event))
                if app.config['SOCKETIO_POLICY_POLL_SECONDS'] > 0 and not registry['watching']:
                    registry['watching'] = True
                    socketio.start_background_task(_watch_sockets, app)
        except Exception:
            registry['clients'].pop(request.sid, None)
            return False

    @socketio.on('disconnect')
    def disconnect(_reason=None):
        with registry['lock']:
            registry['clients'].pop(request.sid, None)


def register_access_policy(app):
    @app.cli.group('access-policy')
    def access_policy_cli():
        """核对 UUID 映射后，以维护数据库角色显式激活入口策略。"""

    @access_policy_cli.command('preview')
    def preview():
        from .serializers import employee_dict

        click.echo(json.dumps({
            'employees': [employee_dict(row) for row in Employee.query.order_by(Employee.created_at).all()],
            'policies': [{'owner_id': row.owner_id, 'mobile_ids': row.mobile_employee_ids,
                          'administrator_ids': row.administrator_employee_ids,
                          'policy_version': row.policy_version, 'is_active': row.is_active}
                         for row in AccessPolicyModel.query.order_by(AccessPolicyModel.policy_version).all()],
        }, ensure_ascii=False, indent=2))

    @access_policy_cli.command('activate')
    @click.option('--owner-id', required=True)
    @click.option('--mobile-id', multiple=True, required=True)
    @click.option('--administrator-id', multiple=True,
                  help='额外高级管理员的既有 UUID；不会停用或删除任何既有账号。')
    def activate(owner_id, mobile_id, administrator_id):
        try:
            result = activate_policy(owner_id, list(mobile_id), list(administrator_id))
        except ApiError as error:
            raise click.ClickException(f'{error.code}: {error.message}') from error
        click.echo(json.dumps(result, ensure_ascii=False))

    @access_policy_cli.command('check-channels')
    @click.option('--employee-id', multiple=True, required=True, help='只读核对既有账号 UUID，不依姓名匹配')
    @click.option('--terminal-code', required=True)
    def check_channels(employee_id, terminal_code):
        from .employee_access import session_ui
        from .models import Terminal

        terminal = Terminal.query.filter_by(code=terminal_code).first()
        result = {'terminal': {'code': terminal_code, 'exists': terminal is not None,
                              'is_active': bool(terminal and terminal.is_active)}, 'employees': []}
        try:
            policy = active_policy()
            result['policy'] = {'owner_id': policy.owner_id, 'mobile_ids': policy.mobile_employee_ids,
                'administrator_ids': policy.administrator_employee_ids, 'policy_version': policy.policy_version}
        except ApiError as error:
            result['policy'] = {'error_code': error.code, 'message': error.message}
        for requested_id in employee_id:
            employee = db.session.get(Employee, requested_id)
            row = {'id': requested_id, 'exists': employee is not None, 'channels': {}}
            if employee:
                row.update(username=employee.username, display_name=employee.display_name, role=employee.role,
                           is_active=employee.is_active, deleted=employee.deleted_at is not None,
                           locked_until=employee.locked_until.isoformat() if employee.locked_until else None)
                for channel in ('desktop', 'web', 'mobile'):
                    try:
                        permissions = session_permissions(employee, channel)
                        if not permissions:
                            raise ApiError('此岗位没有当前入口的业务能力', 403, 'CHANNEL_FORBIDDEN')
                        row['channels'][channel] = {'allowed': True, **session_ui(employee, channel, permissions)}
                    except ApiError as error:
                        row['channels'][channel] = {'allowed': False, 'error_code': error.code, 'message': error.message}
            result['employees'].append(row)
        db.session.rollback()  # Explicit read-only operation; no grants or tokens issued.
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))

    @app.after_request
    def append_policy_headers(response):
        if request.path.startswith('/api/') and request.method != 'OPTIONS' and response.status_code < 500:
            state = BusinessStateModel.query.populate_existing().filter_by(id=1).first()
            if state:
                response.headers['X-Business-Period'] = state.period_id
                response.headers['X-Access-Policy-Version'] = str(state.policy_version)
        return response
