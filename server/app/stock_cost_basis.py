"""Exact current reference costs; receiving receipts remain independent."""
from decimal import Decimal, ROUND_HALF_UP

from .api.errors import ApiError
from .stock_cost_service import cost_amount
from .stock_service import stock_quantity


def _values(amount, basis, factor):
    if amount is None:
        return None, None
    return (amount, amount / factor) if basis == 'package' else (amount * factor, amount)


def stock_cost_values(master):
    factor = master.units_per_package if master.package_unit else Decimal(1)
    amount = master.reference_cost if master.reference_cost is not None else master.unit_cost
    basis = master.cost_basis if master.reference_cost is not None else 'base'
    package, base = _values(amount, basis, factor)
    return dict(reference_cost=f'{amount:.2f}' if amount is not None else None,
                cost_basis=basis if amount is not None else None,
                package_cost=f'{package.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):.2f}' if package is not None else None,
                base_unit_cost=f'{base.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP):.6f}' if base is not None else None)


def plan_stock_cost(master, body):
    """No mutation or password side effects. Caller authenticates before applying."""
    if 'reference_cost' in body or 'cost_basis' in body:
        if not {'reference_cost', 'cost_basis'} <= set(body) or 'unit_cost' in body:
            raise ApiError('成本金额和计价单位须同时填写，不能混用旧成本字段', 400, 'INVALID_STOCK_COST')
        amount, basis = cost_amount(body['reference_cost']), body['cost_basis']
        if basis not in {'base', 'package'}:
            raise ApiError('成本计价单位无效', 400, 'INVALID_STOCK_COST')
    elif 'unit_cost' in body:
        amount, basis = cost_amount(body['unit_cost']), 'base'
    else:
        amount = master.reference_cost if master.reference_cost is not None else master.unit_cost
        basis = master.cost_basis if master.reference_cost is not None else 'base'
    package_unit = body.get('package_unit', master.package_unit)
    factor = stock_quantity(body.get('units_per_package', master.units_per_package)) if package_unit else Decimal(1)
    if amount is not None and basis == 'package' and not package_unit:
        raise ApiError('按包装计价须先填写包装单位', 400, 'INVALID_STOCK_COST')
    package, base = _values(amount, basis, factor)
    if package is not None:
        cost_amount(package.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        cost_amount(base.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    old_amount = master.reference_cost if master.reference_cost is not None else master.unit_cost
    old_basis = master.cost_basis if master.reference_cost is not None else 'base'
    _, old_base = _values(old_amount, old_basis, master.units_per_package if master.package_unit else Decimal(1))
    return dict(reference_cost=amount, cost_basis=basis if amount is not None else None,
                unit_cost=base.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if base is not None else None,
                password_required=old_amount is not None and old_base != base)


def apply_stock_cost(master, plan):
    for key in ('reference_cost', 'cost_basis', 'unit_cost'):
        setattr(master, key, plan[key])
