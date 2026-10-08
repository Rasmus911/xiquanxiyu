from flask import request
from flask_jwt_extended import get_jwt, jwt_required
from flask import Blueprint

from ..auth_service import current_employee
from ..registration_access import can_view_registration_token
from ..registration_service import current_token, register_employee
from .errors import ApiError, success

bp = Blueprint('registration', __name__, url_prefix='/auth')


@bp.post('/registration-token/current')
@jwt_required()
def registration_token_current():
    employee = current_employee()
    claims = get_jwt()
    if not can_view_registration_token(employee, claims.get('client_channel')):
        raise ApiError('无权查看注册授权码', 403, 'REGISTRATION_FORBIDDEN')
    if request.get_data() and request.get_json(silent=True) != {}:
        raise ApiError('授权码查询不接受额外字段', 400, 'INVALID_REGISTRATION_BODY')
    return success(current_token(employee, claims.get('session_id')))


@bp.post('/register')
def register():
    return success(register_employee(request.get_json(silent=True), request.headers.get('Idempotency-Key'),
                                     request.remote_addr), '注册成功，请登录', 201)
