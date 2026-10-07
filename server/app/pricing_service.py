from decimal import Decimal
from copy import deepcopy

from . import financial_lock
from .extensions import db
from .models import CatalogItem, OrderItem, Visit
from .package_service import recompute_visit_billing

CENT = Decimal("0.01")


def _open_visits_with_lock():
    return Visit.query.filter_by(status="open").with_for_update().all()


def reprice_open_catalog_items(catalog: CatalogItem,definition_changed=False):
    financial_lock.serialize_financial_session(db.session)
    visits = _open_visits_with_lock()
    visit_by_id = {visit.id: visit for visit in visits}
    if not visit_by_id:
        return {"item_count": 0, "visit_ids": []}

    items = (
        OrderItem.query.filter(
            OrderItem.visit_id.in_(visit_by_id),
            OrderItem.catalog_item_id == catalog.id,
            OrderItem.status == "active",
        )
        .with_for_update()
        .all()
    )
    changed_visits = set()
    changed_items = 0
    for item in items:
        new_total = (Decimal(catalog.price) * (Decimal(item.quantity)-Decimal(item.covered_quantity or 0))).quantize(CENT)
        if Decimal(item.unit_price) == Decimal(catalog.price) and Decimal(item.total_amount) == new_total and not definition_changed:
            continue
        item.unit_price = catalog.price
        item.total_amount = new_total
        item.version += 1
        if item.kind=='package' and definition_changed:
            item.package_snapshot={'reference_code':catalog.reference_code,**deepcopy(catalog.package_definition)}
        changed_items += 1
        changed_visits.add(item.visit_id)

    for visit_id in changed_visits:
        recompute_visit_billing(db.session,visit_by_id[visit_id])
        visit_by_id[visit_id].version += 1
    return {"item_count": changed_items, "visit_ids": sorted(changed_visits)}


def reprice_open_compensation_items(fee: Decimal):
    financial_lock.serialize_financial_session(db.session)
    visits = _open_visits_with_lock()
    visit_by_id = {visit.id: visit for visit in visits}
    if not visit_by_id:
        return {"item_count": 0, "visit_ids": []}

    items = (
        OrderItem.query.filter(
            OrderItem.visit_id.in_(visit_by_id),
            OrderItem.kind == "compensation",
            OrderItem.status == "active",
        )
        .with_for_update()
        .all()
    )
    changed_visits = set()
    changed_items = 0
    for item in items:
        new_total = (fee * Decimal(item.quantity)).quantize(CENT)
        if Decimal(item.unit_price) == fee and Decimal(item.total_amount) == new_total:
            continue
        item.unit_price = fee
        item.total_amount = new_total
        item.version += 1
        changed_items += 1
        changed_visits.add(item.visit_id)

    for visit_id in changed_visits:
        visit_by_id[visit_id].version += 1
    return {"item_count": changed_items, "visit_ids": sorted(changed_visits)}
