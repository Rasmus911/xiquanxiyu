"""Optional, exact receiving costs, immutable correction history and alert policy."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP

from .api.errors import ApiError
from .audit_service import write_audit
from .extensions import db
from .models import StockCost


def warning_quantity(quantity):
    return (Decimal(quantity) * Decimal('0.15')).quantize(Decimal('0.001'), rounding=ROUND_CEILING)


def cost_amount(raw):
    try:
        if isinstance(raw, bool):
            raise ValueError
        value = Decimal(str(raw))
        if not value.is_finite() or value < 0 or value >= Decimal('10000000000') or value != value.quantize(Decimal('0.01')):
            raise ValueError
        return value.quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        raise ApiError('成本必须是非负金额，最多两位小数且不能超出范围', 400, 'INVALID_STOCK_COST') from None


def current_cost(movement_id):
    return StockCost.query.filter_by(stock_movement_id=movement_id).order_by(StockCost.version.desc()).first()


def cost_dict(record, movement):
    if record is None:
        return None
    return {'id': record.id, 'version': record.version, 'unit_cost': f'{record.unit_cost:.2f}',
            'total_cost': f'{record.total_cost:.2f}',
            'base_unit_cost': f'{(record.unit_cost / movement.conversion_factor):.6f}',
            'operator_id': record.operator_id, 'created_at': record.created_at.isoformat()}


def record_cost(movement, raw, employee, expected_cost_id=None):
    if movement.movement_type not in {'purchase', 'opening'} or movement.quantity <= 0:
        raise ApiError('只有采购和期初入库可以记录成本', 400, 'STOCK_COST_NOT_RECEIVING')
    previous = current_cost(movement.id)
    if (previous.id if previous else None) != expected_cost_id:
        raise ApiError('成本已被修改，请刷新后重新提交', 409, 'STOCK_COST_VERSION_CONFLICT')
    unit_cost = cost_amount(raw)
    total = (unit_cost * movement.input_quantity).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    cost_amount(total)
    record = StockCost(stock_movement_id=movement.id, unit_cost=unit_cost, total_cost=total,
                       version=(previous.version + 1) if previous else 1, operator_id=employee.id)
    db.session.add(record); db.session.flush()
    write_audit('stock.cost', 'stock_movement', movement.id,
                {'before': cost_dict(previous, movement), 'after': cost_dict(record, movement),
                 'input_quantity': f'{movement.input_quantity:.3f}', 'input_unit': movement.input_unit,
                 'conversion_factor': f'{movement.conversion_factor:.3f}'})
    return record
