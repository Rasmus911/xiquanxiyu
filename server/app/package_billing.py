"""Pure, deterministic package quotas. Physical quantities never change here."""
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal('0')
CENT = Decimal('0.01')


@dataclass(frozen=True)
class BillingLine:
    id: str
    catalog_item_id: str
    quantity: Decimal
    unit_price: Decimal
    order_index: int


@dataclass(frozen=True)
class PackageSlot:
    catalog_item_ids: tuple[str, ...]
    quantity: Decimal


def _decimal(value, *, positive=False):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError('finite Decimal required')
    if value < ZERO or (positive and value == ZERO):
        raise ValueError('quantity or price out of bounds')
    return value


def _validate_line(line):
    if not isinstance(line.id, str) or not line.id or not isinstance(line.catalog_item_id, str) or not line.catalog_item_id:
        raise ValueError('line and catalog identities required')
    if type(line.order_index) is not int or line.order_index < 0:
        raise ValueError('nonnegative integer order required')
    _decimal(line.quantity, positive=True)
    _decimal(line.unit_price)


def line_net_total(line: BillingLine, covered: Decimal) -> Decimal:
    _validate_line(line)
    _decimal(covered)
    if covered > line.quantity:
        raise ValueError('included quantity out of bounds')
    return (line.unit_price * (line.quantity - covered)).quantize(CENT)


def allocate_inclusions(lines: list[BillingLine], slots: list[PackageSlot]) -> dict[str, Decimal]:
    coverage = {}
    for line in lines:
        _validate_line(line)
        if line.id in coverage:
            raise ValueError('duplicate order identity')
        coverage[line.id] = ZERO
    seen_catalogs = set()
    for slot in slots:
        _decimal(slot.quantity, positive=True)
        if not slot.catalog_item_ids:
            raise ValueError('empty package slot')
        for catalog_id in slot.catalog_item_ids:
            if not isinstance(catalog_id, str) or not catalog_id or catalog_id in seen_catalogs:
                raise ValueError('duplicate or overlapping package choices')
            seen_catalogs.add(catalog_id)
    ordered = sorted(lines, key=lambda line: (line.order_index, line.id))
    for slot in slots:
        remaining = slot.quantity
        for line in ordered:
            if remaining == ZERO:
                break
            if line.catalog_item_id in slot.catalog_item_ids:
                included = min(remaining, line.quantity - coverage[line.id])
                coverage[line.id] += included
                remaining -= included
    return coverage
