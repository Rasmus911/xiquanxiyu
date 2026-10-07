from decimal import Decimal

from flask import Blueprint, request

from ..access_policy import emit_business_event
from ..audit_service import write_audit
from ..business_period import archive_read
from ..auth_service import current_employee, require_permission, require_any_permission
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..idempotency_service import financial_request_key, guard_financial_request
from ..models import CatalogItem, InventoryMovement
from ..serializers import catalog_dict, iso
from ..validation import decimal_value
from .errors import ApiError, success
from ..models import StockItem, StockMovement, OrderStockConsumption, OrderItem
from ..serializers import stock_item_dict, stock_movement_dict
from ..stock_service import change_balance, legacy_stock, stock_quantity
from ..stock_cost_service import record_cost, cost_amount, current_cost
from ..idempotency_service import idempotency_lookup, idempotency_record_key, idempotency_store

bp = Blueprint("inventory", __name__, url_prefix="/inventory")


def movement_dict(row):
    return {
        "id": row.id,
        "catalog_item_id": row.catalog_item_id,
        "movement_type": row.movement_type,
        "quantity": str(row.quantity),
        "balance_after": str(row.balance_after),
        "reference_type": row.reference_type,
        "reference_id": row.reference_id,
        "operator_id": row.operator_id,
        "note": row.note,
        "created_at": iso(row.created_at),
    }


@bp.get("")
@require_permission("inventory:read")
def list_inventory():
    products = CatalogItem.query.filter_by(kind="product").order_by(CatalogItem.name).all()
    return success([catalog_dict(row) for row in products])


@bp.get("/movements")
@require_permission("inventory:read")
def list_movements():
    with archive_read():
        query = InventoryMovement.query
        if request.args.get("catalog_item_id"):
            query = query.filter_by(catalog_item_id=request.args["catalog_item_id"])
        rows = query.order_by(InventoryMovement.created_at.desc()).limit(500).all()
        return success([movement_dict(row) for row in rows])


@bp.post("/adjust")
@require_permission("inventory:write")
@serialized_financial_write
def adjust_inventory():
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    movement, repeated = adjust_inventory_data(employee, body, key)
    return success(
        movement_dict(movement),
        "已返回原库存结果" if repeated else "库存更新成功",
        200,
    )


def adjust_inventory_data(employee, body, key):
    from .. import financial_lock
    financial_lock.serialize_financial_session(db.session)
    if key:
        key = financial_request_key('inventory:adjust', employee.id, key)
    existing = InventoryMovement.query.filter_by(idempotency_key=key).first() if key else None
    if key:
        guard_financial_request(
            "inventory:adjust", employee, key, body, existing, existing.operator_id if existing else None
        )
    if existing:
        return existing, True
    item = CatalogItem.query.with_for_update().filter_by(id=body.get("catalog_item_id"), kind="product").first()
    if not item:
        raise ApiError("商品不存在", 404, "NOT_FOUND")
    quantity = decimal_value(body.get("quantity"), "数量", scale=3, minimum=None)
    movement_type = str(body.get("movement_type", "adjustment"))
    if movement_type in {"opening", "purchase", "return"} and quantity <= 0:
        raise ApiError("入库数量必须大于 0")
    if movement_type in {"loss"} and quantity > 0:
        quantity = -quantity
    if quantity == 0:
        raise ApiError("调整数量不能为 0")
    master = legacy_stock(item)
    if not master.is_active:
        raise ApiError('库存项目已归档', 409, 'STOCK_NOT_AVAILABLE')
    before_balance = Decimal(master.stock_quantity)
    new_balance = decimal_value(before_balance + quantity, "库存余额", scale=3, minimum=None)
    if new_balance < 0:
        raise ApiError("库存不能小于 0", 409, "INSUFFICIENT_STOCK")
    note = str(body.get("note", "")).strip()
    if not note and movement_type == "purchase":
        note = "采购入库"
    if not note:
        raise ApiError("库存调整必须填写原因或单据号")
    change_balance(master, quantity, employee, movement_type, note, legacy_movement=False)
    movement = InventoryMovement(
        catalog_item_id=item.id,
        movement_type=movement_type,
        quantity=quantity,
        balance_after=new_balance,
        operator_id=employee.id,
        note=note,
        idempotency_key=key or None,
    )
    db.session.add(movement)
    db.session.flush()
    write_audit(
        "inventory.adjust",
        "inventory_movement",
        movement.id,
        {
            "item": item.name,
            "quantity": str(quantity),
            "balance_after": str(new_balance),
            "balance_before": str(before_balance),
            "note": note,
        },
    )
    db.session.commit()
    emit_business_event("inventory.changed", {"catalog_item_id": item.id})
    return movement, False


def _stock_request():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise ApiError('库存参数无效')
    key = str(request.headers.get('Idempotency-Key') or '').strip()
    if not key:
        raise ApiError('缺少幂等请求编号', 400, 'IDEMPOTENCY_REQUIRED')
    employee = current_employee()
    endpoint = request.method + ':' + request.path
    existing = idempotency_lookup(endpoint, employee.id, key)
    return body, key, employee, endpoint, existing


def _stock_result(payload, context, status=200):
    body, key, employee, endpoint, _ = context
    idempotency_store(idempotency_record_key(endpoint, employee.id, key), endpoint, status, {'data': payload})
    db.session.commit()
    emit_business_event('inventory.changed', {'reason': 'stock_changed'})
    return success(payload, '库存更新成功', status)


def _stock_version(master, body):
    if type(body.get('version')) is not int or body['version'] != master.version:
        raise ApiError('库存已更新，请刷新后重新提交', 409, 'STOCK_VERSION_CONFLICT')


def _stock_master(id_):
    master = StockItem.query.filter_by(id=id_).with_for_update().first()
    if not master:
        raise ApiError('库存项目不存在', 404, 'NOT_FOUND')
    return master


def _stock_fields(master, body):
    for field, maximum in [('name',120), ('category',80), ('base_unit',20), ('package_unit',20), ('package_spec',120)]:
        if field in body:
            value = body[field]
            if not isinstance(value, str) or len(value.strip()) > maximum or (field in {'name','base_unit'} and not value.strip()):
                raise ApiError('库存名称或单位无效')
            setattr(master, field, value.strip())
    if 'units_per_package' in body:
        master.units_per_package = stock_quantity(body['units_per_package'])
    # Old clients may still send this field; receiving owns the 15% policy.
    if 'low_stock_threshold' in body:
        stock_quantity(body['low_stock_threshold'], zero=True)


@bp.get('/stock-items')
@require_permission('inventory:read')
def stock_items():
    query = StockItem.query
    if request.args.get('include_inactive') != 'true': query = query.filter_by(is_active=True)
    return success([stock_item_dict(row) for row in query.order_by(StockItem.name, StockItem.id).all()])


@bp.post('/stock-items')
@require_permission('inventory:write')
@serialized_financial_write
def create_stock_item():
    context = _stock_request(); body, _, employee, _, existing = context
    if existing: return success(existing.response_body['data'], '已返回原库存结果', existing.response_status)
    allowed = {'name','category','base_unit','package_unit','units_per_package','package_spec','opening_quantity','opening_unit','low_stock_threshold','unit_cost'}
    if set(body)-allowed or not body.get('name') or not body.get('base_unit'): raise ApiError('库存参数无效')
    master = StockItem(name='', base_unit='', category='默认', package_unit='', package_spec='',
        stock_quantity=Decimal(0), units_per_package=Decimal(1), low_stock_threshold=Decimal(0))
    _stock_fields(master, body)
    unit = body.get('opening_unit', 'base')
    if unit not in {'base','package'} or (unit == 'package' and not master.package_unit): raise ApiError('入库单位无效')
    # Omission permits a zero master; an explicit opening must be positive.
    quantity = stock_quantity(body['opening_quantity']) if 'opening_quantity' in body else Decimal(0)
    factor = master.units_per_package if unit == 'package' else Decimal(1)
    delta = stock_quantity(quantity * factor, zero=True)
    db.session.add(master); db.session.flush()
    if 'unit_cost' in body and not delta:
        raise ApiError('没有入库数量时不能记录成本')
    if delta:
        movement = change_balance(master, delta, employee, 'opening', '期初库存', input_quantity=quantity, input_unit=unit, factor=factor)
        if body.get('unit_cost') is not None:
            record_cost(movement, body['unit_cost'], employee)
    write_audit('stock.create', 'stock_item', master.id, stock_item_dict(master))
    return _stock_result(stock_item_dict(master), context, 201)


@bp.patch('/stock-items/<id_>')
@require_permission('inventory:write')
@serialized_financial_write
def update_stock_item(id_):
    context = _stock_request(); body, _, employee, _, existing = context
    if existing: return success(existing.response_body['data'], '已返回原库存结果')
    if set(body)-{'version','name','category','base_unit','package_unit','units_per_package','package_spec','low_stock_threshold','unit_cost','password'}:
        raise ApiError('库存参数无效')
    master = _stock_master(id_); _stock_version(master, body)
    if not master.is_active: raise ApiError('库存项目已归档', 409, 'STOCK_NOT_AVAILABLE')
    before = stock_item_dict(master)
    next_cost = cost_amount(body['unit_cost']) if 'unit_cost' in body else master.unit_cost
    if master.unit_cost is not None and next_cost != master.unit_cost:
        # Authenticate BEFORE mutating any master fields: failed reauth commits
        # only the account's failure counter, never the requested stock edits.
        from ..auth_service import verify_sensitive_password
        verify_sensitive_password(employee, body.get('password'))
    if body.get('base_unit', master.base_unit) != master.base_unit:
        from ..business_period import archive_read
        with archive_read(None):
            has_movement = StockMovement.query.filter_by(stock_item_id=id_).first() is not None
        if has_movement or master.legacy_catalog_item_id or master.unit_cost is not None:
            raise ApiError('已有流水的基本单位不能更改', 409, 'STOCK_UNIT_IMMUTABLE')
    _stock_fields(master, body); master.unit_cost = next_cost; master.version += 1
    write_audit('stock.update', 'stock_item', master.id, {'before':before, 'after':stock_item_dict(master)})
    return _stock_result(stock_item_dict(master), context)


@bp.delete('/stock-items/<id_>')
@require_permission('inventory:write')
@serialized_financial_write
def archive_stock_item(id_):
    context = _stock_request(); body, _, employee, _, existing = context
    if existing: return success(existing.response_body['data'], '已返回原库存结果')
    if set(body)-{'version','confirm_writeoff'} or ('confirm_writeoff' in body and type(body['confirm_writeoff']) is not bool):
        raise ApiError('归档参数无效')
    master = _stock_master(id_); _stock_version(master, body)
    if not master.is_active: raise ApiError('库存项目已归档',409,'STOCK_NOT_AVAILABLE')
    before = stock_item_dict(master)
    if master.stock_quantity:
        if body.get('confirm_writeoff') is not True: raise ApiError('归档有余额的库存需要确认报损',409,'WRITEOFF_CONFIRMATION_REQUIRED')
        change_balance(master, -master.stock_quantity, employee, 'loss', '归档库存报损')
    master.is_active=False; master.version += 1
    write_audit('stock.archive', 'stock_item', master.id, {'before':before, 'after':stock_item_dict(master)})
    return _stock_result(stock_item_dict(master), context)


@bp.post('/stock-adjust')
@require_permission('inventory:write')
@serialized_financial_write
def stock_adjust():
    context = _stock_request(); body, _, employee, _, existing = context
    if existing: return success(existing.response_body['data'], '已返回原库存结果')
    if set(body)-{'stock_item_id','version','movement_type','quantity','input_unit','reason','unit_cost'}: raise ApiError('库存调整参数无效')
    master = _stock_master(body.get('stock_item_id')); _stock_version(master, body)
    if not master.is_active: raise ApiError('库存项目已归档',409,'STOCK_NOT_AVAILABLE')
    kind = body.get('movement_type'); unit = body.get('input_unit','base')
    reason = body.get('reason')
    if kind not in {'purchase','return','loss','adjust','opening'} or unit not in {'base','package'} or (unit=='package' and not master.package_unit):
        raise ApiError('库存调整类型或单位无效')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>255: raise ApiError('请填写调整原因')
    quantity = stock_quantity(body.get('quantity'), signed=kind=='adjust')
    factor = master.units_per_package if unit=='package' else Decimal(1)
    delta = stock_quantity(quantity * factor, signed=True)
    if kind=='loss': delta = -delta
    if master.stock_quantity + delta < 0: raise ApiError('库存不足',409,'INSUFFICIENT_STOCK')
    movement = change_balance(master, delta, employee, kind, reason.strip(), input_quantity=quantity, input_unit=unit, factor=factor)
    if body.get('unit_cost') is not None:
        record_cost(movement, body['unit_cost'], employee)
    return _stock_result({'stock_item':stock_item_dict(master), 'movement':stock_movement_dict(movement)},context)


@bp.post('/stock-movements/<id_>/cost')
@require_permission('inventory:write')
@serialized_financial_write
def amend_stock_cost(id_):
    context = _stock_request(); body, _, employee, _, existing = context
    if existing: return success(existing.response_body['data'], '已返回原成本结果')
    if not {'unit_cost','expected_cost_id'} <= set(body) or set(body)-{'unit_cost','expected_cost_id','password'}:
        raise ApiError('成本参数无效')
    previous = current_cost(id_)
    if (previous.id if previous else None) != body['expected_cost_id']:
        raise ApiError('成本已被修改，请刷新后重新提交',409,'STOCK_COST_VERSION_CONFLICT')
    next_cost = cost_amount(body['unit_cost'])
    # Inventory is retained across resets; read the original immutable receipt
    # through the trusted archive scope, then append a non-period cost correction.
    with archive_read():
        movement = StockMovement.query.filter_by(id=id_).first()
        if not movement: raise ApiError('入库流水不存在', 404, 'NOT_FOUND')
        values = {column.name: getattr(movement, column.name) for column in StockMovement.__table__.columns}
    from types import SimpleNamespace
    movement = SimpleNamespace(**values)
    if previous is not None and previous.unit_cost != next_cost:
        from ..auth_service import verify_sensitive_password
        verify_sensitive_password(employee, body.get('password'))
    record_cost(movement, body['unit_cost'], employee, body['expected_cost_id'])
    return _stock_result(stock_movement_dict(movement), context)


@bp.get('/stock-movements')
@require_permission('inventory:read')
def stock_movements():
    with archive_read():
        query = StockMovement.query
        if request.args.get('stock_item_id'): query = query.filter_by(stock_item_id=request.args['stock_item_id'])
        return success([stock_movement_dict(row) for row in query.order_by(StockMovement.created_at.desc(),StockMovement.id).limit(500).all()])


@bp.get('/consumables')
@require_any_permission('visit:order','mobile:order')
def consumables():
    fields = {'id','name','category','base_unit','package_spec','stock_quantity','version'}
    return success([{key:value for key,value in stock_item_dict(row).items() if key in fields}
        for row in StockItem.query.filter_by(is_active=True).order_by(StockItem.name,StockItem.id).all()])


@bp.get('/usage')
@require_any_permission('inventory:read','catalog:read')
def stock_usage():
    from sqlalchemy import func
    rows = db.session.query(OrderItem.catalog_item_id, CatalogItem.name, OrderStockConsumption.stock_item_id,
        StockItem.name, StockItem.base_unit, func.count(OrderStockConsumption.id), func.sum(OrderStockConsumption.quantity)).join(
        OrderStockConsumption, OrderStockConsumption.order_item_id==OrderItem.id).join(
        StockItem, StockItem.id==OrderStockConsumption.stock_item_id).join(CatalogItem,CatalogItem.id==OrderItem.catalog_item_id).filter(
        OrderItem.status=='active').group_by(OrderItem.catalog_item_id,CatalogItem.name,OrderStockConsumption.stock_item_id,StockItem.name,StockItem.base_unit).all()
    maxima = {}
    for row in rows: maxima[row[0]] = max(maxima.get(row[0],0),row[5])
    return success([{'catalog_item_id':r[0], 'catalog_name':r[1], 'stock_item_id':r[2], 'stock_name':r[3],
        'base_unit':r[4], 'usage_count':r[5], 'total_quantity':f'{r[6]:.3f}', 'is_most_used':r[5]==maxima[r[0]]} for r in rows])


@bp.post('/photo-import/preview')
@require_permission('inventory:write')
def photo_import_preview():
    from ..stock_import import preview_import
    return success(preview_import(request.get_json(silent=True)), '照片盘点预览；尚未修改库存')


@bp.post('/photo-import/apply')
@require_permission('inventory:write')
@serialized_financial_write
def photo_import_apply():
    from ..stock_import import apply_import
    context = _stock_request()
    body, key, employee, endpoint, existing = context
    # Source and confirmation checks must also run for generic idempotent retries.
    result, repeated = apply_import(body, employee)
    if not existing:
        idempotency_store(idempotency_record_key(endpoint, employee.id, key), endpoint, 200, {'data': result})
    db.session.commit()
    if not repeated:
        emit_business_event('inventory.changed', {'reason': 'photo_import', 'receipt_id': result['receipt_id']})
    return success(result, '已返回原盘点结果' if repeated else '照片盘点已完成')
