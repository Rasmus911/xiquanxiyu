from flask import Blueprint, request

from ..access_policy import emit_business_event
from ..audit_service import write_audit
from ..auth_service import current_employee, require_any_permission, require_permission, verify_sensitive_password
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..catalog_layout import catalog_layout, save_catalog_layout, touch_catalog_layout
from ..models import CatalogItem, OrderItem, Visit, utcnow
from ..pricing_service import reprice_open_catalog_items
from ..package_service import validate_package_definition
from ..ordering_scope import can_sell_catalog, full_ordering
from ..serializers import catalog_dict
from ..validation import decimal_value
from .errors import ApiError, success

bp = Blueprint("catalog", __name__, url_prefix="/catalog")
VALID_KINDS = {"ticket", "service", "product", "compensation", "package"}
VALID_MOBILE_SCOPES = {"frontdesk", "scrub", "rest", "both"}


def _decimal(value, field):
    return decimal_value(value, field, scale=3 if field == "预警库存" else 2)


def _mobile_scope(value):
    scope = str(value or "frontdesk").strip()
    if scope not in VALID_MOBILE_SCOPES:
        raise ApiError("手机端销售范围无效")
    return scope


@bp.get("")
@require_any_permission('visit:read', 'mobile:order', 'catalog:read')
def list_catalog():
    employee = current_employee()
    query = CatalogItem.query.filter(CatalogItem.deleted_at.is_(None))
    if request.args.get("kind"):
        query = query.filter_by(kind=request.args["kind"])
    if request.args.get("active") != "false":
        query = query.filter_by(is_active=True)
    rows = query.order_by(CatalogItem.sort_order, CatalogItem.id).all()
    if not full_ordering(employee):
        rows = [row for row in rows if can_sell_catalog(employee, row)]
    return success([catalog_dict(row, employee=employee) for row in rows])


@bp.post("")
@require_permission("catalog:write")
@serialized_financial_write
def create_item():
    body = request.get_json(silent=True) or {}
    kind = str(body.get("kind", "")).strip()
    name = str(body.get("name", "")).strip()
    if kind not in VALID_KINDS or not name:
        raise ApiError("项目类型或名称无效")
    if kind=='package': validate_package_definition(db.session,body.get('package_definition'))
    elif 'package_definition' in body: raise ApiError('只有套票可以设置包含定义',400,'INVALID_PACKAGE')
    row = CatalogItem(
        kind=kind,
        category=str(body.get("category", "默认")).strip() or "默认",
        name=name,
        mobile_scope=_mobile_scope(body.get("mobile_scope")),
        price=_decimal(body.get("price", 0), "价格"),
        stock_tracked=bool(body.get("stock_tracked", kind == "product")),
        low_stock_threshold=_decimal(body.get("low_stock_threshold", 0), "预警库存"),
        sort_order=int(body.get("sort_order", 0)),
        package_definition=body.get('package_definition') if kind=='package' else None,
    )
    db.session.add(row)
    db.session.flush()
    if row.kind == 'product' and row.stock_tracked:
        from ..stock_service import legacy_stock
        legacy_stock(row)
    touch_catalog_layout(db.session)
    write_audit("catalog.create", "catalog_item", row.id, catalog_dict(row))
    db.session.commit()
    emit_business_event("catalog.changed", {"item_id": row.id})
    return success(catalog_dict(row, employee=current_employee()), "项目创建成功", 201)


@bp.patch("/<item_id>")
@require_permission("catalog:write")
@serialized_financial_write
def update_item(item_id):
    row = CatalogItem.query.filter_by(id=item_id).with_for_update().first()
    if not row or row.deleted_at:
        raise ApiError("项目不存在", 404, "NOT_FOUND")
    body = request.get_json(silent=True) or {}
    before = catalog_dict(row)
    if 'package_definition' in body:
        if row.kind!='package': raise ApiError('只有套票可以设置包含定义',400,'INVALID_PACKAGE')
        validate_package_definition(db.session,body['package_definition'])
        row.package_definition=body['package_definition']
    if "name" in body:
        row.name = str(body["name"]).strip()
    if "category" in body:
        row.category = str(body["category"]).strip() or "默认"
    if "mobile_scope" in body:
        row.mobile_scope = _mobile_scope(body["mobile_scope"])
    if "price" in body:
        row.price = _decimal(body["price"], "价格")
    if "is_active" in body:
        row.is_active = bool(body["is_active"])
    if "stock_tracked" in body:
        row.stock_tracked = bool(body["stock_tracked"])
    if "low_stock_threshold" in body:
        row.low_stock_threshold = _decimal(body["low_stock_threshold"], "预警库存")
    if "sort_order" in body:
        row.sort_order = int(body["sort_order"])
    stock_reactivated = False
    if 'is_active' in body and row.is_active:
        from ..stock_service import reactivate_catalog_stock
        stock_reactivated = reactivate_catalog_stock(row)
    row.version += 1
    touch_catalog_layout(db.session)
    repriced = reprice_open_catalog_items(row,definition_changed='package_definition' in body) if {'price','package_definition'} & set(body) else {"item_count": 0, "visit_ids": []}
    write_audit(
        "catalog.update",
        "catalog_item",
        row.id,
        {"before": before, "after": catalog_dict(row), "repriced_open_bills": repriced},
    )
    db.session.commit()
    emit_business_event("catalog.changed", {"item_id": row.id})
    if stock_reactivated:
        emit_business_event('inventory.changed',{'catalog_item_id':row.id,'reason':'catalog_reactivated'})
    if repriced["visit_ids"]:
        emit_business_event("visit.changed", {"reason": "catalog_price_changed", **repriced})
    return success(catalog_dict(row, employee=current_employee()))


@bp.delete('/<item_id>')
@require_permission('catalog:delete')
@serialized_financial_write
def delete_item(item_id):
    employee = current_employee()
    verify_sensitive_password(employee, (request.get_json(silent=True) or {}).get('password'))
    row = CatalogItem.query.filter_by(id=item_id).with_for_update().first()
    if not row:
        raise ApiError('项目不存在', 404, 'NOT_FOUND')
    if row.deleted_at:
        db.session.commit()
        return success(catalog_dict(row), '项目已归档')
    packages = CatalogItem.query.filter_by(kind='package', deleted_at=None).all()
    if any(row.id in slot.get('catalog_item_ids', [])
            for package in packages if package.id != row.id
            for slot in (package.package_definition or {}).get('slots', [])):
        raise ApiError('项目仍被套票引用，请先修改套票', 409, 'CATALOG_DELETE_BLOCKED')
    if OrderItem.query.join(Visit, Visit.id == OrderItem.visit_id).filter(
            OrderItem.catalog_item_id == row.id, OrderItem.status == 'active',
            Visit.status.in_(['open', 'settling'])).first():
        raise ApiError('项目仍有未完成账单，请先处理', 409, 'CATALOG_DELETE_BLOCKED')
    open_packages = OrderItem.query.join(Visit, Visit.id == OrderItem.visit_id).filter(
        OrderItem.kind == 'package', OrderItem.status == 'active', Visit.status.in_(['open', 'settling'])).all()
    if any(row.id in slot.get('catalog_item_ids', []) for line in open_packages
            for slot in (line.package_snapshot or {}).get('slots', [])):
        raise ApiError('项目仍被未完成套票账单引用，请先处理', 409, 'CATALOG_DELETE_BLOCKED')
    before = catalog_dict(row)
    row.deleted_at = utcnow()
    row.is_active = False
    row.version += 1
    touch_catalog_layout(db.session)
    write_audit('catalog.delete', 'catalog_item', row.id,
        {'before': before, 'after': {**catalog_dict(row), 'deleted_at': row.deleted_at.isoformat()}})
    db.session.commit()
    emit_business_event('catalog.changed', {'item_id': row.id})
    return success(catalog_dict(row), '项目已归档')


@bp.get('/layout')
@require_permission('catalog:layout')
@serialized_financial_write
def read_layout():
    result = catalog_layout(db.session)
    db.session.commit()
    return success(result)


@bp.put('/layout')
@require_permission('catalog:layout')
@serialized_financial_write
def update_layout():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict) or set(body) - {'revision', 'ids'}:
        raise ApiError('排列参数无效')
    result = save_catalog_layout(db.session, current_employee(), body.get('revision'), body.get('ids'))
    db.session.commit()
    emit_business_event('catalog.changed', {'reason': 'layout'})
    return success(result, '排列已同步')
