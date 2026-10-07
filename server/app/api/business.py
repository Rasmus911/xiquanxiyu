from flask import Blueprint, request
from flask_jwt_extended import get_jwt, jwt_required

from ..auth_service import current_employee, require_permission
from ..business_period import business_state_data
from .errors import success

bp = Blueprint('business', __name__, url_prefix='/business')


@bp.get('/state')
@jwt_required()
def state():
    return success(business_state_data(current_employee()))


@bp.get('/reset/preview')
@require_permission('business:reset')
def reset_preview():
    from ..reset_service import preview_reset
    return success(preview_reset(current_employee(), get_jwt()))


@bp.post('/reset/tasks')
@require_permission('business:reset')
def reset_create():
    from ..reset_service import create_reset_task, dispatch_reset, task_data
    task = create_reset_task(current_employee(), get_jwt(), request.get_json(silent=True) or {})
    data = task_data(task)
    if task.status == 'queued':
        dispatch_reset(task.id)
    return success(data, status=202)


@bp.get('/archives')
@require_permission('business:archive')
def archives():
    from ..models import ResetTaskModel
    rows = ResetTaskModel.query.filter_by(status='completed').order_by(ResetTaskModel.created_at.desc())
    page = max(1, request.args.get('page', 1, type=int))
    return success([{'period_id': row.old_period_id, 'reset_id': row.id,
                     'summary': row.context.get('summary', {}),
                     'closed_at': row.updated_at.isoformat(), 'backup': {
                         key: row.backup[key] for key in ('sha256', 'size')}}
                    for row in rows.offset((page - 1) * 50).limit(50).all()])


@bp.get('/archives/<period_id>/evidence')
@require_permission('business:archive')
def archive_evidence(period_id):
    from datetime import date, datetime
    from decimal import Decimal

    from ..business_period import archive_read, current_period_id
    from ..extensions import db
    from ..models import AuditLog, BusinessPeriod, PeriodMixin, ResetTaskModel
    from .errors import ApiError
    period = db.session.get(BusinessPeriod, period_id)
    if not period or not period.closed_at or period_id == current_period_id():
        raise ApiError('归档经营期不存在', 404, 'NOT_FOUND')
    models = {mapper.local_table.name: mapper.class_ for mapper in db.Model.registry.mappers
              if issubclass(mapper.class_, PeriodMixin)}
    # Idempotency responses can contain credentials from future endpoints: no
    # implicit export of that envelope. Financial evidence is explicit tables.
    models.pop('idempotency_records', None)
    models['audit_logs'] = AuditLog
    model = models.get(request.args.get('table', 'members'))
    if not model:
        raise ApiError('证据类型无效', 400, 'BAD_REQUEST')
    page = max(1, request.args.get('page', 1, type=int))
    size = min(500, max(1, request.args.get('page_size', 100, type=int)))
    def serialize(row):
        result = {}
        for column in model.__table__.columns:
            value = getattr(row, column.name)
            result[column.name] = (str(value) if isinstance(value, Decimal) else
                                   value.isoformat() if isinstance(value, (date, datetime)) else value)
        return result
    with archive_read(period_id):
        query = model.query
        if model is AuditLog:
            task = ResetTaskModel.query.filter_by(old_period_id=period_id, status='completed').one()
            end = AuditLog.query.filter_by(action='business.reset', entity_id=task.id).one().chain_index
            previous = ResetTaskModel.query.filter_by(new_period_id=period_id, status='completed').first()
            start = (AuditLog.query.filter_by(action='business.reset', entity_id=previous.id).one().chain_index
                     if previous else 0)
            query = query.filter(AuditLog.chain_index > start, AuditLog.chain_index <= end)
            query = query.order_by(AuditLog.chain_index)
        else:
            query = query.order_by(*model.__mapper__.primary_key)
        rows = query.offset((page - 1) * size).limit(size + 1).all()
        data = {'period_id': period_id, 'table': model.__tablename__, 'page': page,
                'has_more': len(rows) > size, 'rows': [serialize(row) for row in rows[:size]]}
    return success(data)


@bp.get('/reset/tasks')
@require_permission('business:reset')
def reset_tasks():
    from ..models import ResetTaskModel
    from ..reset_service import task_data
    query = ResetTaskModel.query.filter_by(owner_id=current_employee().id)
    if request.args.get('idempotency_key'):
        query = query.filter_by(idempotency_key=request.args['idempotency_key'])
    page = max(1, request.args.get('page', 1, type=int))
    return success([task_data(row) for row in query.order_by(ResetTaskModel.created_at.desc())
                    .offset((page - 1) * 50).limit(50).all()])


@bp.get('/reset/tasks/<task_id>')
@require_permission('business:reset')
def reset_task(task_id):
    from ..models import ResetTaskModel
    from ..reset_service import task_data
    from .errors import ApiError
    task = ResetTaskModel.query.filter_by(id=task_id, owner_id=current_employee().id).first()
    if not task:
        raise ApiError('任务不存在', 404, 'NOT_FOUND')
    return success(task_data(task))
