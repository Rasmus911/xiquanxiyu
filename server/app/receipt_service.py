"""Transactional print references and once-only attempts; never redo a sale."""
from flask_jwt_extended import get_jwt

from .api.errors import ApiError
from .audit_service import write_audit
from .auth_service import has_permission
from .extensions import db
from .models import SystemSetting, Wristband, new_uuid, utcnow
from .ordering_scope import STAFF_AREAS, bath_area
from .receipt_models import ServicePrintAttempt, ServicePrintJob, SettlementPrintAttempt
from .receipt_retention import as_utc, next_midnight, require_current_receipt
from .serializers import decimal_str


def service_reference(job):
    return {'id':job.id, 'kind':'order', 'created_at':as_utc(job.created_at).isoformat(),
            'expires_at':next_midnight(job.created_at).isoformat()}


def create_service_print_job(session, employee, visit, items, terminal_id, submission_key):
    if employee.role not in STAFF_AREAS or get_jwt().get('client_channel') == 'mobile':
        return None
    now = utcnow()
    band = session.get(Wristband,visit.wristband_id)
    setting = session.query(SystemSetting).filter_by(key='store_name').first()
    job = ServicePrintJob(id=new_uuid(),created_at=now,visit_id=visit.id,
        employee_id=employee.id,terminal_id=terminal_id,submission_key=submission_key,
        bath_area=bath_area(band))
    job.snapshot = {'receipt_kind':'order','job_id':job.id,'store_name':setting.value if setting else '平泉市溪泉洗浴',
        'wristband_number':band.number,'bath_area':job.bath_area,
        'employee_name':employee.display_name,'employee_username':employee.username,
        'created_at':now.isoformat(),'expires_at':next_midnight(now).isoformat(),
        'items':[{'name':item.name_snapshot,'quantity':str(item.quantity),
                  'total_amount':decimal_str(item.total_amount)} for item in items]}
    session.add(job)
    session.flush()
    return job


def require_service_receipt(employee, job):
    if not has_permission(employee,'print:order'):
        raise ApiError('无权访问下单小票',403,'PERMISSION_DENIED')
    if (not has_permission(employee,'*') and job.bath_area not in STAFF_AREAS.get(employee.role,set())):
        raise ApiError('无权访问该浴区下单小票',403,'PERMISSION_DENIED')
    require_current_receipt(job)


def begin_attempt(employee, job, body, receipt, service):
    if (not isinstance(body,dict) or set(body) != {'request_key','mode'}
            or not isinstance(body['request_key'],str) or not body['request_key'].strip()
            or len(body['request_key'])>100 or not isinstance(body['mode'],str)
            or body['mode'] not in {'automatic','manual'}):
        raise ApiError('打印请求编号或模式无效',400,'INVALID_PRINT_ATTEMPT')
    require_current_receipt(job)
    model = ServicePrintAttempt if service else SettlementPrintAttempt
    from .idempotency_service import idempotency_record_key
    key = idempotency_record_key('print-attempt:'+('order' if service else 'settlement')+':'+job.id,
                                 employee.id,body['request_key'])
    existing = model.query.filter_by(request_key=key).first()
    if existing:
        if existing.job_id != job.id or existing.mode != body['mode']:
            raise ApiError('打印请求编号不能用于不同内容',409,'IDEMPOTENCY_CONFLICT')
        return {'id':existing.id,'print_allowed':False,'receipt':receipt},200
    if body['mode']=='automatic':
        automatic = model.query.filter_by(job_id=job.id,mode='automatic').first()
        if automatic:
            return {'id':automatic.id,'print_allowed':False,'receipt':receipt},200
    attempt = model(job_id=job.id,request_key=key,employee_id=employee.id,
        terminal_id=get_jwt()['terminal_id'],mode=body['mode'])
    db.session.add(attempt)
    db.session.flush()
    write_audit('receipt.order_attempt' if service else 'receipt.settlement_attempt',
                'service_print_job' if service else 'print_job',job.id,
                {'attempt_id':attempt.id,'mode':attempt.mode})
    db.session.commit()
    return {'id':attempt.id,'print_allowed':True,'receipt':receipt},201


def finish_attempt(employee, job, attempt_id, body, service):
    require_current_receipt(job)
    if (not isinstance(body,dict) or set(body)-{'success','error'} or type(body.get('success')) is not bool
            or ('error' in body and not isinstance(body['error'],str))):
        raise ApiError('打印结果格式无效',400,'INVALID_PRINT_RESULT')
    model = ServicePrintAttempt if service else SettlementPrintAttempt
    attempt = model.query.populate_existing().filter_by(id=attempt_id,job_id=job.id).with_for_update().first()
    if not attempt:
        raise ApiError('打印尝试不存在',404,'NOT_FOUND')
    if attempt.employee_id != employee.id or attempt.terminal_id != get_jwt()['terminal_id']:
        raise ApiError('只能回写本人当前终端的打印结果',403,'PERMISSION_DENIED')
    error = None if body['success'] else body.get('error','打印失败')[:500]
    if attempt.finished_at is not None:
        if attempt.success != body['success'] or attempt.error != error:
            raise ApiError('已经记录的打印结果不能覆盖',409,'PRINT_RESULT_CONFLICT')
    else:
        attempt.success = body['success']; attempt.error = error; attempt.finished_at = utcnow()
        job.attempts += 1
        job.status = 'success' if attempt.success else 'failed'
        job.last_error = error
        if attempt.success: job.printed_at = attempt.finished_at
        write_audit('receipt.order_print' if service else 'receipt.print',
            'service_print_job' if service else 'print_job',job.id,
            {'attempt_id':attempt.id,'success':attempt.success,'attempt':job.attempts,'error':error})
        db.session.commit()
    return {'id':job.id,'status':job.status,'attempts':job.attempts}
