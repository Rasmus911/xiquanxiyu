"""Authenticated Excel stocktake endpoints. No direct DB replacement."""
from io import BytesIO
from flask import Blueprint, send_file

from ..auth_service import require_permission
from ..audit_service import write_audit
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..inventory_excel_service import (apply_preview, build_preview, mapping_token,
                                      pending_dict, unresolved_rows)
from ..inventory_xlsx import export_inventory_xlsx
from ..models import StockImportPending, StockImportResolution, StockItem
from ..serializers import stock_item_dict
from ..stock_cost_basis import apply_stock_cost, plan_stock_cost
from ..stock_service import change_balance, stock_quantity
from .errors import ApiError, success
from .inventory import _stock_request, _stock_result, _stock_fields

bp = Blueprint('inventory_excel', __name__, url_prefix='/inventory/excel')


@bp.get('/export')
@require_permission('inventory:read')
def export():
    rows = StockItem.query.filter_by(is_active=True).order_by(StockItem.name, StockItem.id).limit(1001).all()
    try: raw = export_inventory_xlsx([{**stock_item_dict(row), 'mapping_token': mapping_token(row)} for row in rows])
    except ValueError as error: raise ApiError(str(error)) from None
    return send_file(BytesIO(raw), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='溪泉库存盘点表.xlsx', max_age=0)


@bp.post('/preview')
@require_permission('inventory:write')
def preview():
    from flask import request
    from ..auth_service import current_employee
    body = request.get_json(silent=True) or {}
    if set(body) != {'source_base64', 'source_sha256'}: raise ApiError('预览参数无效')
    return success(build_preview(current_employee(), body))


@bp.post('/apply')
@require_permission('inventory:write')
@serialized_financial_write
def apply():
    context = _stock_request(); body, _, employee, _, existing = context
    if existing: return success(existing.response_body['data'], '已返回原Excel导入结果')
    if set(body) - {'source_base64', 'source_sha256', 'preview_token', 'confirmed_rows', 'password'}:
        raise ApiError('导入参数无效')
    return _stock_result(apply_preview(employee, body), context)


@bp.get('/pending')
@require_permission('inventory:read')
def pending():
    return success([pending_dict(row) for row in unresolved_rows()])


def _pending(id_):
    row = StockImportPending.query.filter_by(id=id_).first()
    if row is None: raise ApiError('待补资料条目不存在', 404, 'NOT_FOUND')
    if StockImportResolution.query.filter_by(pending_id=row.id).first():
        raise ApiError('该条目已处理，请刷新', 409, 'PENDING_ALREADY_RESOLVED')
    return row


@bp.post('/pending/<id_>/complete')
@require_permission('inventory:write')
@serialized_financial_write
def complete(id_):
    context = _stock_request(); body, _, employee, _, existing = context
    if existing: return success(existing.response_body['data'], '已返回原补齐资料结果', existing.response_status)
    if set(body) - {'base_unit', 'package_unit', 'units_per_package', 'password'} or not body.get('base_unit'):
        raise ApiError('请填写基本单位与包装资料')
    row = _pending(id_)
    if row.target_stock_item_id:
        master = StockItem.query.filter_by(id=row.target_stock_item_id).with_for_update().first()
        if master is None or not master.is_active or master.version != row.target_version or master.base_unit != '原销售单位':
            raise ApiError('原库存已变化，请取消此待补行后重新导入', 409, 'STOCK_VERSION_CONFLICT')
    else:
        if StockItem.query.filter_by(name=row.name).first(): raise ApiError('同名库存已存在，请取消待补条目并重新导入', 409, 'STOCK_NAME_CONFLICT')
        master = StockItem(name=row.name, base_unit='', category='默认', package_unit='', package_spec='',
                           units_per_package=1, stock_quantity=0, low_stock_threshold=0)
    before = stock_item_dict(master) if row.target_stock_item_id else None
    cost_plan = plan_stock_cost(master, {**body, **({'reference_cost':str(row.package_cost),
        'cost_basis':'package' if body.get('package_unit','').strip() else 'base'} if row.package_cost is not None else {})})
    if cost_plan and cost_plan['password_required']:
        from ..auth_service import verify_sensitive_password
        verify_sensitive_password(employee, body.get('password'))
    _stock_fields(master, body)
    if master.base_unit == '原销售单位': raise ApiError('请确认实际基本单位')
    if cost_plan: apply_stock_cost(master, cost_plan)
    db.session.add(master); db.session.flush()
    delta = row.base_quantity - master.stock_quantity
    if delta:
        change_balance(master, delta, employee, 'adjust' if row.target_stock_item_id else 'opening', 'Excel补齐资料人工盘点',
                       reference_type='stock_import_pending', reference_id=row.id)
    elif row.target_stock_item_id: master.version += 1
    resolution = StockImportResolution(pending_id=row.id, outcome='completed', stock_item_id=master.id, created_by_id=employee.id)
    db.session.add(resolution)
    write_audit('stock.excel_complete', 'stock_import_pending', row.id,
                {'source': pending_dict(row), 'before':before, 'stock_item': stock_item_dict(master)})
    return _stock_result(stock_item_dict(master), context, 200 if row.target_stock_item_id else 201)


@bp.post('/pending/<id_>/cancel')
@require_permission('inventory:write')
@serialized_financial_write
def cancel(id_):
    context = _stock_request(); body, _, employee, _, existing = context
    if existing: return success(existing.response_body['data'], '已返回原取消结果')
    if body: raise ApiError('取消参数无效')
    row = _pending(id_)
    db.session.add(StockImportResolution(pending_id=row.id, outcome='cancelled', created_by_id=employee.id))
    write_audit('stock.excel_cancel', 'stock_import_pending', row.id, pending_dict(row))
    return _stock_result({'id': row.id, 'cancelled': True}, context)
