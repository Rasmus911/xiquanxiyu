"""Owner-authorized reset orchestration; secrets never enter durable task data."""
import hmac
import threading
from dataclasses import asdict
from datetime import timedelta

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from .access_policy import is_owner
from .api.errors import ApiError
from .audit_service import sign_evidence
from .auth_service import verify_sensitive_password
from .business_period import business_state_data
from .extensions import db
from .models import CatalogItem, StockItem, Member, MemberPass, OrderItem, ResetTaskModel, Visit, new_uuid, utcnow


def _owner(employee):
    if not is_owner(employee):
        raise ApiError('仅店主可执行此操作', 403, 'OWNER_REQUIRED')


def _signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='business-reset-preview-v1')


def _binding(employee, claims, state):
    return {'owner_id': employee.id, 'session_id': claims.get('session_id'),
            'client_channel': claims.get('client_channel'), 'period_id': state['period_id'],
            'business_revision': state['business_revision'], 'policy_version': state['policy_version'],
            'session_version': employee.session_version}


def period_summary():
    members = Member.query.all()
    masters = StockItem.query.all()
    mapped = {row.legacy_catalog_item_id for row in masters if row.legacy_catalog_item_id}
    stock = [*masters, *[row for row in CatalogItem.query.filter_by(stock_tracked=True).all() if row.id not in mapped]]
    visits = Visit.query.filter(Visit.status.in_(['open', 'settling'])).all()
    unsettled = OrderItem.query.filter(OrderItem.visit_id.in_([row.id for row in visits]),
                                      OrderItem.status == 'active').all()
    return {'members': len(members), 'stored_balance': f'{sum(row.balance for row in members):.2f}',
            'remaining_passes': sum(row.remaining_count for row in MemberPass.query.all()),
            'active_visits': len(visits), 'unsettled_amount': f'{sum(row.total_amount for row in unsettled):.2f}',
            'stock_items': len(stock), 'stock_quantity': f'{sum(row.stock_quantity for row in stock):.3f}',
            'stock_preserved': True}


def preview_reset(employee, claims):
    _owner(employee)
    state = business_state_data(employee)
    if state['maintenance']:
        raise ApiError('正在维护，请稍后重试', 503, 'BUSINESS_MAINTENANCE')
    return {'state': state, 'confirmation_token': _signer().dumps(_binding(employee, claims, state)),
            'expires_at': (utcnow() + timedelta(seconds=300)).isoformat(), 'summary': period_summary()}


def task_data(task):
    data = {key: getattr(task, key) for key in ('id', 'idempotency_key', 'status', 'stage',
            'old_period_id', 'new_period_id', 'error_code', 'message') if getattr(task, key) is not None}
    if task.backup:
        data['backup'] = {key: task.backup[key] for key in ('sha256', 'size')}
    return data


def create_reset_task(employee, claims, payload):
    _owner(employee)
    key = payload.get('idempotency_key')
    if not isinstance(key, str) or not 8 <= len(key) <= 100:
        raise ApiError('请求编号无效', 400, 'RESET_CONFIRMATION_INVALID')
    if payload.get('username') != employee.username:
        verify_sensitive_password(employee, '')
    verify_sensitive_password(employee, payload.get('password'))
    if payload.get('confirmation') != '重置当前经营数据':
        raise ApiError('请完整输入确认文字', 400, 'RESET_CONFIRMATION_INVALID')
    # Authenticated owner may recover the existing result after re-login/reset.
    existing = ResetTaskModel.query.filter_by(idempotency_key=key, owner_id=employee.id).first()
    if existing:
        return existing
    try:
        proof = _signer().loads(payload.get('confirmation_token', ''), max_age=300)
    except (BadSignature, SignatureExpired, TypeError):
        raise ApiError('确认凭据无效或已过期', 400, 'RESET_CONFIRMATION_INVALID') from None
    state = business_state_data(employee)
    expected = _binding(employee, claims, state)
    if any(proof.get(k) != expected[k] for k in ('owner_id', 'session_id', 'client_channel')):
        raise ApiError('确认凭据不属于本会话', 400, 'RESET_CONFIRMATION_INVALID')
    if proof != expected:
        raise ApiError('经营数据已改变，请重新预览', 409, 'RESET_PREVIEW_STALE')
    if state['maintenance']:
        raise ApiError('正在维护，请稍后重试', 503, 'BUSINESS_MAINTENANCE')
    context = {'proof': proof, 'summary': period_summary()}
    context['signature'] = sign_evidence(context)
    owner_id = employee.id
    db.session.commit()
    from .business_barrier import control_connection
    with control_connection() as connection:
        with connection.begin():
            if connection.dialect.name == 'postgresql':
                from sqlalchemy.dialects.postgresql import insert as insert_task
            else:
                from sqlalchemy.dialects.sqlite import insert as insert_task
            connection.execute(insert_task(ResetTaskModel).values(id=new_uuid(), idempotency_key=key,
                owner_id=owner_id, old_period_id=state['period_id'], context=context)
                .on_conflict_do_nothing(index_elements=['idempotency_key']))
            task_id = connection.execute(select(ResetTaskModel.id).where(
                ResetTaskModel.idempotency_key == key)).scalar_one()
    db.session.expire_all()
    task = db.session.get(ResetTaskModel, task_id)
    if task.owner_id != owner_id:
        raise ApiError('请求编号冲突', 409, 'IDEMPOTENCY_CONFLICT')
    return task


def valid_task_proof(context):
    signed = {key: value for key, value in context.items() if key != 'signature'}
    return hmac.compare_digest(str(context.get('signature', '')), sign_evidence(signed))


def _transaction(connection):
    if connection.dialect.name == 'sqlite':
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        return connection.get_transaction()
    return connection.begin()


def _row(connection, model, identifier):
    return connection.execute(select(model.__table__).where(model.id == identifier)).mappings().one()


def _validate_worker_task(connection, task, state):
    from .models import AccessPolicyModel, Employee, RevokedSession
    proof = task['context'].get('proof', {})
    employee = _row(connection, Employee, task['owner_id'])
    policies = connection.execute(select(AccessPolicyModel.__table__).where(
        AccessPolicyModel.is_active.is_(True))).mappings().all()
    if (not valid_task_proof(task['context']) or proof.get('owner_id') != task['owner_id']
            or len(policies) != 1 or policies[0]['owner_id'] != task['owner_id']
            or policies[0]['policy_version'] != proof.get('policy_version')
            or not employee['is_active'] or employee['session_version'] != proof.get('session_version')
            or employee['locked_until'] is not None
            or connection.execute(select(RevokedSession.id).where(
                RevokedSession.id == proof.get('session_id'))).first()):
        raise ApiError('重置授权已失效', 403, 'RESET_CONFIRMATION_INVALID')
    if (state['period_id'] != task['old_period_id'] or proof.get('period_id') != state['period_id']
            or proof.get('business_revision') != state['business_revision']
            or proof.get('policy_version') != state['policy_version']):
        raise ApiError('经营数据已改变，请重新预览', 409, 'RESET_PREVIEW_STALE')
    if state['maintenance']:
        raise ApiError('存在待核对的维护任务', 503, 'BUSINESS_MAINTENANCE')


def _finish_reset(connection, task, backup):
    from .audit_service import write_audit
    from .models import (
        BusinessPeriod,
        BusinessStateModel,
        Employee,
        ResetEventModel,
        Shift,
        Wristband,
    )
    now, new_period = utcnow(), new_uuid()
    old_period, task_id = task['old_period_id'], task['id']
    state = _row(connection, BusinessStateModel, 1)
    if state['period_id'] != old_period or state['maintenance_reset_id'] != task_id or not state['maintenance']:
        raise RuntimeError('Reset ownership changed')
    connection.execute(update(Visit.__table__).where(Visit.period_id == old_period,
        Visit.status.in_(['open', 'settling'])).values(status='reset_closed', closed_at=now,
        version=Visit.version + 1))
    connection.execute(update(Shift.__table__).where(Shift.period_id == old_period,
        Shift.status == 'open').values(status='reset_closed', closed_at=now,
        close_note=f'经营重置 {task_id}', version=Shift.version + 1))
    # Inventory remains continuous across business periods. Neither quantities,
    # versions nor immutable movement evidence change during a business reset.
    connection.execute(update(Wristband).values(status='available', note=None, version=Wristband.version + 1))
    connection.execute(update(Employee).values(session_version=Employee.session_version + 1))
    connection.execute(insert(BusinessPeriod).values(id=new_period))
    connection.execute(update(BusinessPeriod).where(BusinessPeriod.id == old_period).values(closed_at=now))
    event = {'period_id': new_period, 'policy_version': state['policy_version'], 'reset_id': task_id}
    # Reuse the SAME physical connection and surrounding transaction for the
    # append-only audit chain. No global scoped-session transaction is involved.
    audit_session = Session(bind=connection, join_transaction_mode='rollback_only')
    try:
        write_audit('business.reset', 'reset_task', task_id,
                    {**event, 'old_period_id': old_period, 'backup_sha256': backup.sha256},
                    employee_id=task['owner_id'], session=audit_session)
        audit_session.flush()
    finally:
        audit_session.close()
    connection.execute(update(BusinessStateModel).where(BusinessStateModel.id == 1).values(
        period_id=new_period, business_revision=BusinessStateModel.business_revision + 1,
        maintenance=False, maintenance_reset_id=None))
    connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task_id).values(
        status='completed', stage='completed', new_period_id=new_period, backup=asdict(backup)))
    connection.execute(insert(ResetEventModel).values(reset_id=task_id, data=event))


def _fail_task(connection, task_id, code):
    from .models import BusinessStateModel
    with _transaction(connection):
        connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task_id,
            ResetTaskModel.status != 'completed').values(status='failed', stage='failed',
            error_code=code, message='重置未完成；请查看任务并重新核对经营数据'))
        connection.execute(update(BusinessStateModel).where(BusinessStateModel.id == 1,
            BusinessStateModel.maintenance_reset_id == task_id).values(maintenance=False, maintenance_reset_id=None))


def run_reset_task(task_id):
    from .business_barrier import control_connection, exclusive_barrier
    from .models import BusinessStateModel
    from .reset_backup import create_database_backup
    db.session.remove()
    with control_connection() as connection:
        with _transaction(connection):
            connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task_id,
                ResetTaskModel.status == 'queued').values(status='waiting', stage='waiting'))
        with exclusive_barrier(connection, task_id, wait=True):
            phase = 'validation'
            try:
                with _transaction(connection):
                    task = _row(connection, ResetTaskModel, task_id)
                    if task['status'] in {'completed', 'failed'}:
                        return
                    if task['status'] not in {'queued', 'waiting'}:
                        phase = 'recovery_required'
                        raise RuntimeError('Interrupted task requires explicit recovery, never replay')
                    state = _row(connection, BusinessStateModel, 1)
                    _validate_worker_task(connection, task, state)
                    connection.execute(update(BusinessStateModel).where(BusinessStateModel.id == 1).values(
                        maintenance=True, maintenance_reset_id=task_id))
                    connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task_id).values(
                        status='backing_up', stage='backing_up'))
                phase = 'backup'
                backup = create_database_backup(connection, task_id, task['old_period_id'])
                connection.commit()  # finish backup metadata SELECT transaction
                with _transaction(connection):
                    connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task_id).values(
                        status='resetting', stage='resetting', backup=asdict(backup)))
                phase = 'reset'
                with _transaction(connection):
                    _finish_reset(connection, task, backup)
            except Exception as error:
                if connection.invalidated or phase == 'recovery_required':
                    # Never reconnect and continue. The durable marker is left for
                    # startup recovery under a fresh exclusive barrier.
                    raise
                connection.rollback()
                code = error.code if isinstance(error, ApiError) else (
                    'RESET_BACKUP_FAILED' if phase == 'backup' else 'RESET_FAILED')
                _fail_task(connection, task_id, code)
                current_app.logger.error('Reset task %s failed during %s (%s)', task_id, phase, code)
    deliver_reset_events()
    if current_app.config.get('RESET_PRIVATE_DIR'):
        from .security_spool import import_spool_events
        try:
            import_spool_events()
        except Exception:
            # The reset outcome is already committed. Keep the failed spool
            # evidence for retry at startup/next reset; never rewrite that outcome.
            current_app.logger.error('Reset finished; security spool import requires retry')


def deliver_reset_events():
    from .access_policy import invalidate_sockets
    from .business_barrier import control_connection, exclusive_barrier
    from .models import ResetEventModel
    with control_connection() as connection:
        with exclusive_barrier(connection, 'event-delivery'):
            with _transaction(connection):
                events = connection.execute(select(ResetEventModel.__table__).where(
                    ResetEventModel.delivered_at.is_(None))).mappings().all()
                for event in events:
                    invalidate_sockets(event['data'], event='business.reset')
                    connection.execute(update(ResetEventModel).where(ResetEventModel.id == event['id']).values(
                        delivered_at=utcnow()))


def recover_reset_tasks():
    """Explicit server startup only; reconcile evidence, never re-execute a reset."""
    from .business_barrier import control_connection, exclusive_barrier
    from .models import BusinessStateModel, ResetEventModel
    db.session.remove()
    with control_connection() as connection:
        with exclusive_barrier(connection, 'recovery'):
            conflict = False
            with _transaction(connection):
                state = _row(connection, BusinessStateModel, 1)
                tasks = connection.execute(select(ResetTaskModel.__table__).where(
                    ResetTaskModel.status.in_(['queued', 'waiting', 'backing_up', 'resetting', 'completed'])
                )).mappings().all()
                events = {event['reset_id']: event for event in connection.execute(
                    select(ResetEventModel.__table__)).mappings()}

                def committed_result(task):
                    event = events.get(task['id'])
                    return (task['new_period_id'] is not None and event is not None
                            and event['data'].get('period_id') == task['new_period_id']
                            and event['data'].get('reset_id') == task['id'])

                successors = {task['old_period_id']: task['new_period_id'] for task in tasks
                              if task['status'] == 'completed' and committed_result(task)}

                def reaches_current(period):
                    visited = set()
                    while period != state['period_id']:
                        if period in visited or period not in successors:
                            return False
                        visited.add(period)
                        period = successors[period]
                    return True

                if state['maintenance'] and state['maintenance_reset_id'] not in {task['id'] for task in tasks}:
                    conflict = True
                for task in tasks:
                    if conflict:
                        break
                    event = events.get(task['id'])
                    committed = committed_result(task)
                    if committed and reaches_current(task['new_period_id']):
                        connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task['id'])
                                           .values(status='completed', stage='completed'))
                    elif (task['status'] in {'queued', 'waiting', 'backing_up', 'resetting'}
                          and event is None and task['new_period_id'] is None and
                          (state['period_id'] == task['old_period_id'] or task['status'] in {'queued', 'waiting'})):
                        connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task['id']).values(
                            status='failed', stage='recovered_not_executed', error_code='RESET_INTERRUPTED'))
                    else:
                        connection.execute(update(BusinessStateModel).where(BusinessStateModel.id == 1)
                                           .values(maintenance=True))
                        conflict = True
                        break
                    if state['maintenance_reset_id'] == task['id']:
                        connection.execute(update(BusinessStateModel).where(BusinessStateModel.id == 1).values(
                            maintenance=False, maintenance_reset_id=None))
                if conflict:
                    connection.execute(update(BusinessStateModel).where(BusinessStateModel.id == 1)
                                       .values(maintenance=True))
            if conflict:
                raise RuntimeError('Conflicting reset evidence; manual recovery required')
    deliver_reset_events()


def dispatch_reset(task_id):
    if not current_app.config.get('RESET_WORKER_ENABLED'):
        return
    app = current_app._get_current_object()
    # Native threads are required even if a hosting wrapper monkey-patches
    # threading. run.py itself never monkey-patches gevent.
    try:
        from gevent.monkey import is_module_patched
        if is_module_patched('threading'):
            raise RuntimeError('Reset worker requires native unpatched threading')
    except ImportError:
        pass
    def work():
        with app.app_context():
            try:
                run_reset_task(task_id)
            except Exception:
                app.logger.exception('Reset worker stopped; persisted task requires recovery')
    threading.Thread(target=work, name=f'reset-{task_id}', daemon=True).start()
