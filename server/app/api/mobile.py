from decimal import Decimal

from flask import Blueprint, request

from ..access_policy import emit_business_event
from ..audit_service import write_audit
from ..auth_service import current_employee, has_permission, require_any_permission, require_permission
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..idempotency_service import idempotency_lookup, idempotency_record_key, idempotency_store
from ..models import CatalogItem, OrderItem, Visit, Wristband
from ..ordering_scope import bath_area, can_read_visit, can_sell_catalog, require_order_catalog, require_order_target
from ..serializers import catalog_dict, iso, order_item_dict, wristband_area
from .errors import ApiError, success
from .inventory import adjust_inventory_data, movement_dict
from .reports import _range as report_range
from .reports import item_report_data, summary_data, trend_data, insights_data
from .visits import _create_order_selection, _load_visit, _package_request, _quantity, _validate_catalog_quantity
from ..stock_service import normalize_consumption
from ..ordering_scope import full_ordering

bp = Blueprint("mobile", __name__, url_prefix="/mobile")

ROLE_POLICIES = {
    'inventory': {'label': '库管', 'bath_areas': {'male','female'}, 'catalog_scopes': {'frontdesk','scrub','rest','both'}},
    "admin": {
        "label": "系统管理员",
        "bath_areas": {"male", "female"},
        "catalog_scopes": {"frontdesk", "scrub", "rest", "both"},
    },
    "male_scrubber": {
        "label": "男浴搓澡师",
        "bath_areas": {"male"},
        "catalog_scopes": {"scrub", "both"},
    },
    "female_scrubber": {
        "label": "女浴搓澡师",
        "bath_areas": {"female"},
        "catalog_scopes": {"scrub", "both"},
    },
    "floor_attendant": {
        "label": "三层服务员",
        "bath_areas": {"male", "female"},
        "catalog_scopes": {"rest", "both"},
    },
}


def _policy(employee):
    policy = ROLE_POLICIES.get(employee.role)
    if not policy:
        raise ApiError("该账号不能登录手机点单端", 403, "MOBILE_ROLE_REQUIRED")
    return policy


def _has_management_access(employee):
    from ..access_policy import policy_enforced

    if policy_enforced():
        from ..employee_access import is_protected_employee
        return employee.role == 'admin' and is_protected_employee(employee)
    return employee.role == "admin" and bool(employee.mobile_full_access)


def _capabilities(employee):
    full = _has_management_access(employee)
    from ..access_policy import policy_enforced

    reports = has_permission(employee, 'report:read') and (full or employee.role in ('cashier', 'inventory'))
    inventory = has_permission(employee, 'inventory:write') and (policy_enforced() or full or employee.role == 'inventory')
    return {
        'orders_view': has_permission(employee, 'mobile:order'),
        "order_all": full or employee.role == 'inventory',
        "catalog_all": full or employee.role == 'inventory',
        "reports_view": reports,
        "inventory_manage": inventory,
        "reports": reports,
        "inventory_add": inventory,
    }


def _require_capability(employee, capability):
    if not _capabilities(employee)[capability]:
        raise ApiError("该账号没有执行此手机业务操作的权限", 403, "PERMISSION_DENIED")


def _active_visit_amounts(visit_ids):
    amounts = {visit_id: Decimal("0.00") for visit_id in visit_ids}
    if not visit_ids:
        return amounts
    rows = OrderItem.query.filter(
        OrderItem.visit_id.in_(visit_ids),
        OrderItem.status == "active",
    ).all()
    for row in rows:
        amounts[row.visit_id] += Decimal(row.total_amount)
    return amounts


@bp.get("/bootstrap")
@require_any_permission('mobile:order', 'inventory:read')
def bootstrap():
    employee = current_employee()
    policy = _policy(employee)
    visits = Visit.query.filter_by(status="open").order_by(Visit.opened_at).all()
    wristband_ids = [visit.wristband_id for visit in visits]
    wristbands = (
        Wristband.query.filter(
            Wristband.id.in_(wristband_ids),
            Wristband.status == "in_use",
            Wristband.is_active.is_(True),
        ).all()
        if wristband_ids
        else []
    )
    wristband_by_id = {row.id: row for row in wristbands}
    allowed_visits = [
        visit
        for visit in visits
        if visit.wristband_id in wristband_by_id
        and can_read_visit(employee, wristband_by_id[visit.wristband_id], visit)
    ]
    amounts = _active_visit_amounts([visit.id for visit in allowed_visits])
    packages={line.visit_id:line.catalog_item_id for line in OrderItem.query.filter(
        OrderItem.visit_id.in_([visit.id for visit in allowed_visits]),
        OrderItem.kind=='package',OrderItem.status=='active').all()}
    bands = [
        {
            "number": wristband_by_id[visit.wristband_id].number,
            "bath_area": bath_area(wristband_by_id[visit.wristband_id]),
            "visit_id": visit.id,
            "version": visit.version,
            "opened_at": iso(visit.opened_at),
            "amount": f"{amounts[visit.id]:.2f}",
            "package_catalog_item_id":packages.get(visit.id),
        }
        for visit in allowed_visits
    ]
    bands.sort(key=lambda row: row["number"])

    catalog_query = CatalogItem.query.filter(
        CatalogItem.is_active.is_(True),
        CatalogItem.kind.in_(["service", "product", "package"]),
    )
    if not full_ordering(employee):
        catalog_query = catalog_query.filter(CatalogItem.mobile_scope.in_(policy["catalog_scopes"]))
    catalog = catalog_query.order_by(
        CatalogItem.kind,
        CatalogItem.sort_order,
        CatalogItem.name,
    ).all()
    return success(
        {
            "employee": {
                "id": employee.id,
                "username": employee.username,
                "display_name": employee.display_name,
                "role": employee.role,
                "role_label": policy["label"],
                "capabilities": _capabilities(employee),
            },
            "wristbands": bands,
            "catalog": [catalog_dict(row,employee=employee) for row in catalog if can_sell_catalog(employee, row)],
        }
    )


@bp.get("/management/report")
@require_permission('report:read')
def management_report():
    employee = current_employee()
    _require_capability(employee, "reports_view")
    start, end = report_range()
    return success(
        {
            "summary": summary_data(start, end),
            "items": item_report_data(start, end),
            "trend": trend_data(start, end),
            "insights": insights_data(start, end),
        }
    )


@bp.get("/management/inventory")
@require_permission('inventory:read')
def management_inventory():
    employee = current_employee()
    _require_capability(employee, "inventory_manage")
    products = (
        CatalogItem.query.filter_by(kind="product", is_active=True)
        .order_by(CatalogItem.category, CatalogItem.name)
        .all()
    )
    return success([catalog_dict(row) for row in products])


@bp.post("/management/inventory/add")
@require_permission('inventory:write')
@serialized_financial_write
def management_inventory_add():
    employee = current_employee()
    _require_capability(employee, "inventory_manage")
    key = str(request.headers.get("Idempotency-Key", "")).strip()
    if not key:
        raise ApiError("缺少幂等请求编号", 400, "IDEMPOTENCY_REQUIRED")
    body = dict(request.get_json(silent=True) or {})
    body["movement_type"] = "purchase"
    movement, repeated = adjust_inventory_data(employee, body, key)
    return success(
        movement_dict(movement),
        "已返回原库存结果" if repeated else "库存入库成功",
        200 if repeated else 201,
    )


@bp.post("/visits/<visit_id>/items")
@require_permission("mobile:order")
@serialized_financial_write
def create_order(visit_id):
    employee = current_employee()
    policy = _policy(employee)
    raw_key = str(request.headers.get("Idempotency-Key", "")).strip()
    if not raw_key:
        raise ApiError("缺少幂等请求编号", 400, "IDEMPOTENCY_REQUIRED")
    record_key = idempotency_record_key("mobile-order", employee.id, f"{visit_id}:{raw_key}")
    visit = _load_visit(visit_id, lock=True)
    wristband = Wristband.query.with_for_update().filter_by(id=visit.wristband_id).first()
    require_order_target(employee, wristband, visit)
    existing = idempotency_lookup("mobile-order", employee.id, f"{visit_id}:{raw_key}")
    if existing:
        return success(existing.response_body["items"], "已返回原点单结果")
    body = request.get_json(silent=True) or {}
    requested_items = body.get("items")
    from .visits import _validate_visit_version
    _validate_visit_version(visit, body)
    if not isinstance(requested_items, list) or not requested_items:
        raise ApiError("请选择至少一个项目")
    if len(requested_items) > 50:
        raise ApiError("一次最多可添加 50 个项目")

    normalized = []
    for row in requested_items:
        if not isinstance(row, dict) or not row.get("catalog_item_id"):
            raise ApiError("点单项目格式错误")
        if set(row)-{'catalog_item_id','quantity','inventory_mode','inventory_consumption'}:
            raise ApiError('点单不接受客户端金额或包含额度',400,'INVALID_ORDER')
        normalized.append(
            {
                "catalog_item_id": str(row["catalog_item_id"]),
                "quantity": _quantity(row.get("quantity", 1)),
                "inventory_consumption": normalize_consumption(row),
            }
        )

    if visit.status != "open":
        raise ApiError("当前手牌不能加项", 409, "VISIT_NOT_OPEN")
    if not wristband or wristband.status != "in_use":
        raise ApiError("当前手牌未激活", 409, "WRISTBAND_NOT_ACTIVE")

    catalog_ids = sorted({row["catalog_item_id"] for row in normalized})
    catalogs = (
        CatalogItem.query.with_for_update()
        .filter(CatalogItem.id.in_(catalog_ids), CatalogItem.is_active.is_(True))
        .order_by(CatalogItem.id)
        .all()
    )
    catalog_by_id = {row.id: row for row in catalogs}
    if len(catalog_by_id) != len(catalog_ids):
        raise ApiError("部分项目不存在或已停用", 404, "ITEM_NOT_AVAILABLE")

    required_stock = {}
    for row in normalized:
        catalog = catalog_by_id[row["catalog_item_id"]]
        if catalog.kind not in {"service", "product", "package"}:
            raise ApiError("该项目不能在手机端销售", 403, "CATALOG_FORBIDDEN")
        require_order_catalog(employee, catalog)
        _validate_catalog_quantity(catalog, row["quantity"])
        if row['inventory_consumption'] is None and catalog.kind == "product" and catalog.stock_tracked:
            required_stock[catalog.id] = required_stock.get(catalog.id, Decimal("0")) + row["quantity"]
    for row in normalized:
        row['service_employee_id']=employee.id if catalog_by_id[row['catalog_item_id']].kind=='service' else None
    items = _create_order_selection(visit,normalized,catalog_by_id,employee,body)
    visit.version += 1
    payload = [order_item_dict(item) for item in items]
    write_audit(
        "mobile.order_create",
        "visit",
        visit.id,
        {
            "wristband_number": wristband.number,
            "role": employee.role,
            "items": payload,
        },
    )
    idempotency_store(record_key, f"/api/mobile/visits/{visit_id}/items", 201, {"items": payload})
    db.session.commit()
    emit_business_event("visit.changed", {"visit_id": visit.id, "source": "mobile"})
    if required_stock or any(row['inventory_consumption'] for row in normalized):
        emit_business_event("inventory.changed", {"reason": "mobile_sale"})
    return success(payload, f"手牌 {wristband.number} 点单成功", 201)


@bp.route('/visits/<visit_id>/package',methods=['POST','DELETE'])
@require_permission('visit:package')
@serialized_financial_write
def change_package(visit_id):
    return _package_request(visit_id)
