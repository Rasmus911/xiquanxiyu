"""One base-unit balance for independent masters and compatible legacy writers.

Callers hold the existing financial serialization and commit the whole operation.
"""
from decimal import Decimal, InvalidOperation

from .api.errors import ApiError
from .audit_service import write_audit
from .extensions import db
from .models import CatalogItem, InventoryMovement, OrderStockConsumption, StockItem, StockMovement


def stock_quantity(raw, *, signed=False, zero=False):
    try:
        value = Decimal(str(raw))
        if (not value.is_finite() or abs(value) >= Decimal('1000000000')
                or value != value.quantize(Decimal('0.001'))
                or (not signed and value < 0) or (not zero and value == 0)):
            raise ValueError
        return value.quantize(Decimal('0.001'))
    except (ValueError, TypeError, InvalidOperation):
        raise ApiError('库存数量必须为有效数字，最多三位小数且不能超出范围', 400, 'INVALID_STOCK_QUANTITY') from None


def legacy_stock(catalog, *, lock=True):
    query = StockItem.query.filter_by(legacy_catalog_item_id=catalog.id)
    row = (query.with_for_update() if lock else query).first()
    if row is None:
        # No unit guesses: legacy quantities already use their original sale unit.
        row = StockItem(name=catalog.name, category=catalog.category, base_unit='原销售单位',
            stock_quantity=catalog.stock_quantity, low_stock_threshold=catalog.low_stock_threshold,
            legacy_catalog_item_id=catalog.id, is_active=catalog.is_active)
        db.session.add(row)
        db.session.flush()
    return row


def reactivate_catalog_stock(catalog):
    """Only repair catalog-disabled legacy masters, never an explicit stock archive.

    stock.archive is immutable, period-independent evidence written by the only
    public stock archival path, including zero-balance archival.
    """
    from .models import AuditLog
    from .serializers import stock_item_dict
    if catalog.kind != 'product' or not catalog.stock_tracked or not catalog.is_active:
        return False
    master = legacy_stock(catalog)
    if master.is_active or AuditLog.query.filter_by(action='stock.archive',entity_type='stock_item',entity_id=master.id).first():
        return False
    before = stock_item_dict(master)
    master.is_active = True
    master.version += 1
    write_audit('stock.catalog_reactivate','stock_item',master.id,
        {'catalog_item_id':catalog.id,'before':before,'after':stock_item_dict(master)})
    return True


def normalize_consumption(body):
    if 'inventory_mode' not in body and 'inventory_consumption' not in body:
        return None
    if body.get('inventory_mode') != 'manual' or not isinstance(body.get('inventory_consumption'), list):
        raise ApiError('请选择手工耗用明细或明确不耗用', 400, 'INVALID_INVENTORY_CONSUMPTION')
    raw = body['inventory_consumption']
    if len(raw) > 50:
        raise ApiError('一次最多选择50种耗材', 400, 'INVALID_INVENTORY_CONSUMPTION')
    result, seen = [], set()
    for row in raw:
        if (not isinstance(row, dict) or set(row) != {'stock_item_id', 'quantity'}
                or not isinstance(row['stock_item_id'], str) or not row['stock_item_id']
                or row['stock_item_id'] in seen):
            raise ApiError('耗材编号或数量无效，不允许重复', 400, 'INVALID_INVENTORY_CONSUMPTION')
        seen.add(row['stock_item_id'])
        result.append({'stock_item_id': row['stock_item_id'], 'quantity': stock_quantity(row['quantity'])})
    return result


def prepare_consumption(rows, catalogs, *, recorded_returns=None):
    """Lock requested + returned masters together and validate net availability.

    recorded_returns comes only from a locked old package's immutable records;
    this plans availability without returning anything before full validation.
    """
    recorded_returns = recorded_returns or {}
    required = {}
    for row in rows:
        catalog = catalogs[row['catalog_item_id']]
        selection = row.get('inventory_consumption')
        row['_legacy_consumption'] = selection is None
        if selection is None:
            selection = ([{'stock_item_id': legacy_stock(catalog,lock=False).id, 'quantity': row['quantity']}]
                         if catalog.kind == 'product' and catalog.stock_tracked else [])
            row['inventory_consumption'] = selection
        for selected in selection:
            required[selected['stock_item_id']] = required.get(selected['stock_item_id'], Decimal(0)) + selected['quantity']
    affected = sorted(set(required) | set(recorded_returns))
    masters = StockItem.query.filter(StockItem.id.in_(affected)).order_by(StockItem.id).with_for_update().all() if affected else []
    by_id = {row.id: row for row in masters}
    if len(by_id) != len(affected):
        raise ApiError('耗材不存在或已归档', 404, 'STOCK_NOT_AVAILABLE')
    for id_, quantity in required.items():
        master = by_id.get(id_)
        if master is None or not master.is_active:
            raise ApiError('耗材不存在或已归档', 404, 'STOCK_NOT_AVAILABLE')
        if master.stock_quantity + recorded_returns.get(id_,Decimal(0)) < quantity:
            raise ApiError(f'库存不足：{master.name}', 409, 'INSUFFICIENT_STOCK')
    return by_id


def change_balance(master, delta, employee, movement_type, reason, *, input_quantity=None,
                   input_unit='base', factor=Decimal('1'), reference_type=None, reference_id=None,
                   legacy_movement=True):
    delta = stock_quantity(delta, signed=True)
    before = Decimal(master.stock_quantity)
    after = stock_quantity(before + delta, zero=True)
    master.stock_quantity = after
    if movement_type in {'purchase', 'opening'} and delta > 0:
        from .stock_cost_service import warning_quantity
        master.low_stock_threshold = warning_quantity(delta)
    master.version += 1
    movement = StockMovement(stock_item_id=master.id, movement_type=movement_type, quantity=delta,
        balance_before=before, balance_after=after, input_quantity=input_quantity if input_quantity is not None else abs(delta),
        input_unit=input_unit, conversion_factor=factor, base_unit_snapshot=master.base_unit,
        package_unit_snapshot=master.package_unit, operator_id=employee.id, reason=reason,
        reference_type=reference_type, reference_id=reference_id)
    db.session.add(movement)
    if master.legacy_catalog_item_id:
        catalog = db.session.get(CatalogItem, master.legacy_catalog_item_id)
        catalog.stock_quantity = after
        catalog.low_stock_threshold = master.low_stock_threshold
        catalog.version += 1
        if legacy_movement:
            db.session.add(InventoryMovement(catalog_item_id=catalog.id, movement_type=movement_type,
                quantity=delta, balance_after=after, operator_id=employee.id, note=reason,
                reference_type=reference_type, reference_id=reference_id))
    db.session.flush()
    write_audit('stock.' + movement_type, 'stock_movement', movement.id,
        {'stock_item_id': master.id, 'before': f'{before:.3f}', 'after': f'{after:.3f}',
         'quantity': f'{delta:.3f}', 'reference_id': reference_id, 'reason': reason})
    return movement


def consume_order(item, selection, masters, employee, legacy=False):
    for row in selection:
        master = masters[row['stock_item_id']]
        db.session.add(OrderStockConsumption(order_item_id=item.id, stock_item_id=master.id,
            quantity=row['quantity'], stock_name_snapshot=master.name, base_unit_snapshot=master.base_unit))
        change_balance(master, -row['quantity'], employee, 'sale', '手牌消费：' + item.name_snapshot,
            reference_type='order_item', reference_id=item.id)


def return_order_stock(item, employee, reason, movement_type='void_return'):
    records = OrderStockConsumption.query.filter_by(order_item_id=item.id).all()
    if not records:
        # Historical pre-migration orders have their exact deduction in old evidence.
        originals = InventoryMovement.query.filter_by(reference_type='order_item', reference_id=item.id, movement_type='sale').all()
        for movement in originals:
            catalog = CatalogItem.query.filter_by(id=movement.catalog_item_id).with_for_update().one()
            master = legacy_stock(catalog)
            change_balance(master, -movement.quantity, employee, movement_type, reason,
                reference_type='order_item', reference_id=item.id, legacy_movement=True)
        return
    masters = {row.id: row for row in StockItem.query.filter(StockItem.id.in_(sorted(r.stock_item_id for r in records))).order_by(StockItem.id).with_for_update().all()}
    for record in records:
        master = masters[record.stock_item_id]
        legacy = InventoryMovement.query.filter_by(reference_id=item.id, reference_type='order_item', movement_type='sale', catalog_item_id=master.legacy_catalog_item_id).first() is not None if master.legacy_catalog_item_id else False
        change_balance(master, record.quantity, employee, movement_type, reason,
            reference_type='order_item', reference_id=item.id, legacy_movement=legacy)
