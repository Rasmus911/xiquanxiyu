from flask import Blueprint, request
from flask_jwt_extended import get_jwt

from ..access_policy import emit_business_event
from ..auth_service import current_employee, require_permission
from ..employee_access import can_bind_wristband
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..models import Wristband, WristbandChipBinding
from ..wristband_reader_service import CURRENT_BAND_NUMBERS, binding_data, change_binding
from .errors import ApiError, success

bp = Blueprint('wristband_reader', __name__, url_prefix='/wristband-reader')


def binding_actor():
    employee = current_employee()
    if not can_bind_wristband(employee, get_jwt().get('client_channel')):
        raise ApiError('当前账号无手牌 ID 录入权限', 403, 'FORBIDDEN')
    return employee


@bp.get('/bindings')
@require_permission('wristband:bind')
def list_bindings():
    binding_actor()
    bindings = {row.wristband_id: row for row in WristbandChipBinding.query.all()}
    bands = Wristband.query.filter(Wristband.is_active.is_(True), Wristband.number.in_(CURRENT_BAND_NUMBERS)).order_by(Wristband.number).all()
    return success([binding_data(band, bindings.get(band.id)) for band in bands])


@bp.route('/bindings/<band_id>', methods=['PUT', 'DELETE'])
@require_permission('wristband:bind')
@serialized_financial_write
def save_binding(band_id):
    employee = binding_actor()
    result = change_binding(employee, get_jwt()['terminal_id'], band_id,
        request.get_json(silent=True) or {}, deleting=request.method == 'DELETE')
    db.session.commit()
    emit_business_event('wristbands.changed', {'reason': 'chip_binding', 'wristband_id': band_id})
    return success(result)


@bp.post('/scan')
@require_permission('visit:write')
@serialized_financial_write
def scan():
    if get_jwt().get('client_channel') not in {'desktop', 'web'}:
        raise ApiError('手机端不能刷卡开牌', 403, 'FORBIDDEN')
    from ..wristband_reader_service import scan_wristband
    result = scan_wristband(current_employee(), request.get_json(silent=True) or {})
    db.session.commit()
    if result['opened']:
        emit_business_event('wristbands.changed', {'reason': 'chip_open', 'wristband_number': result['wristband_number']})
    return success(result)
