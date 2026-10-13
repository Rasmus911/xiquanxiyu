from flask import Blueprint, request

from ..auth_service import current_employee, has_permission, require_permission
from ..extensions import db
from ..models import utcnow
from ..ordering_scope import STAFF_AREAS
from ..receipt_models import ServicePrintJob
from ..receipt_retention import as_utc, business_day_bounds
from ..receipt_service import begin_attempt, finish_attempt, require_service_receipt, service_reference
from .errors import ApiError, success

bp = Blueprint('service_print',__name__,url_prefix='/service-print-jobs')


def pagination():
    try:
        page = int(request.args.get('page','1')); size = int(request.args.get('page_size','10'))
    except ValueError:
        raise ApiError('分页参数无效')
    if page<1 or size not in {10,15,20,50}:
        raise ApiError('分页参数无效')
    return page,size


def load_job(job_id, lock=False):
    query = ServicePrintJob.query.populate_existing().filter_by(id=job_id)
    if lock: query = query.with_for_update()
    job = query.first()
    if not job: raise ApiError('下单小票不存在或已过期清理',404,'NOT_FOUND')
    require_service_receipt(current_employee(),job)
    return job


@bp.get('')
@require_permission('print:order')
def list_jobs():
    employee = current_employee()
    page,size = pagination(); now = utcnow(); start,end = business_day_bounds(now)
    query = ServicePrintJob.query.filter(ServicePrintJob.created_at>=start,ServicePrintJob.created_at<end)
    if not has_permission(employee,'*'):
        query = query.filter(ServicePrintJob.bath_area.in_(STAFF_AREAS.get(employee.role,set())))
    total = query.count()
    rows = query.order_by(ServicePrintJob.created_at.desc(),ServicePrintJob.id.desc()).offset((page-1)*size).limit(size).all()
    return success({'items':[dict(service_reference(job),wristband_number=job.snapshot['wristband_number'],
        employee_name=job.snapshot['employee_name'],employee_username=job.snapshot['employee_username'],
        status=job.status,attempts=job.attempts,last_error=job.last_error) for job in rows],
        'total':total,'page':page,'page_size':size,'server_time':as_utc(now).isoformat(),'expires_at':end.isoformat()})


@bp.get('/<job_id>/receipt')
@require_permission('print:order')
def receipt(job_id):
    return success(load_job(job_id).snapshot)


@bp.post('/<job_id>/attempts')
@require_permission('print:order')
def attempt(job_id):
    employee = current_employee(); job = load_job(job_id,lock=True)
    result,status = begin_attempt(employee,job,request.get_json(silent=True),job.snapshot,True)
    return success(result,status=status)


@bp.post('/<job_id>/attempts/<attempt_id>/result')
@require_permission('print:order')
def result(job_id,attempt_id):
    employee = current_employee(); job = load_job(job_id,lock=True)
    return success(finish_attempt(employee,job,attempt_id,request.get_json(silent=True),True))
