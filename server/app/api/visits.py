from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

from ..access_policy import emit_business_event
from ..audit_service import write_audit
from ..auth_service import current_employee, has_permission, require_permission
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..idempotency_service import (
    idempotency_lookup,
    idempotency_record_key,
    idempotency_store,
)
from ..models import CatalogItem, InventoryMovement, OrderItem, Visit, Wristband
from ..ordering_scope import can_read_visit, require_order_catalog, require_order_target
from ..package_service import cancel_visit_package, recompute_visit_billing, set_visit_package
from ..serializers import order_item_dict, visit_dict
from ..validation import decimal_value
from .errors import ApiError, success
from ..stock_service import normalize_consumption, prepare_consumption, consume_order, return_order_stock

bp = Blueprint("visits", __name__, url_prefix="/visits")


def _package_request(visit_id):
    employee=current_employee()
    body=request.get_json(silent=True) or {}
    allowed={'catalog_item_id','version','idempotency_key','confirm_replace'} if request.method=='POST' else {'version','idempotency_key'}
    if (not isinstance(body,dict) or set(body)-allowed or 'version' not in body
            or (request.method=='POST' and (not isinstance(body.get('catalog_item_id'),str) or not body['catalog_item_id']))
            or ('confirm_replace' in body and type(body['confirm_replace']) is not bool)):
        raise ApiError('套票参数无效，不接受客户端金额',400,'INVALID_PACKAGE')
    raw_key=str(request.headers.get('Idempotency-Key') or body.get('idempotency_key') or '').strip()
    if not raw_key: raise ApiError('缺少幂等请求编号',400,'IDEMPOTENCY_REQUIRED')
    visit=_load_visit(visit_id,lock=True)
    require_order_target(employee,db.session.get(Wristband,visit.wristband_id),visit)
    endpoint=request.method+':'+request.path
    existing=idempotency_lookup(endpoint,employee.id,raw_key)
    if existing: return success(existing.response_body['data'],'已返回原套票操作结果')
    if visit.status!='open': raise ApiError('当前账单不能更改套票',409,'VISIT_NOT_OPEN')
    _validate_visit_version(visit,body)
    if request.method=='POST':
        catalog=CatalogItem.query.filter_by(id=body.get('catalog_item_id'),is_active=True,kind='package').with_for_update().first()
        set_visit_package(db.session,visit,catalog,employee,confirm_replace=body.get('confirm_replace',False))
    else: cancel_visit_package(db.session,visit,employee)
    visit.version+=1
    db.session.flush()
    rows=OrderItem.query.filter_by(visit_id=visit.id).order_by(OrderItem.created_at,OrderItem.id).all()
    payload=visit_dict(visit,db.session.get(Wristband,visit.wristband_id),rows)
    idempotency_store(idempotency_record_key(endpoint,employee.id,raw_key),endpoint,200,{'data':payload})
    db.session.commit()
    emit_business_event('visit.changed',{'visit_id':visit.id,'reason':'package_changed'})
    emit_business_event('wristbands.changed',{'wristband_id':visit.wristband_id})
    return success(payload,'套票已更新')


@bp.route('/<visit_id>/package',methods=['POST','DELETE'])
@require_permission('visit:package')
@serialized_financial_write
def change_package(visit_id):
    return _package_request(visit_id)


@bp.patch('/<visit_id>/ticket')
@require_permission('visit:write')
@serialized_financial_write
def change_ticket(visit_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    if set(body)-{'ticket_catalog_item_id','version','idempotency_key'} or not isinstance(body.get('ticket_catalog_item_id'),str):
        raise ApiError('请选择服务器上的门票，不接受客户端金额',400,'INVALID_TICKET')
    raw_key = str(request.headers.get('Idempotency-Key') or body.get('idempotency_key') or '').strip()
    if not raw_key: raise ApiError('缺少幂等请求编号',400,'IDEMPOTENCY_REQUIRED')
    visit = _load_visit(visit_id,lock=True)
    endpoint = f'visits:{visit_id}:ticket'
    existing = idempotency_lookup(endpoint,employee.id,raw_key)
    if existing: return success(existing.response_body['data'],'已返回原票种变更结果',existing.response_status)
    if visit.status!='open': raise ApiError('当前账单不能更改门票',409,'VISIT_NOT_OPEN')
    if 'version' not in body: raise ApiError('缺少账单版本',400,'VERSION_REQUIRED')
    _validate_visit_version(visit,body)
    from .wristbands import _active_ticket
    ticket = _active_ticket(body['ticket_catalog_item_id'])
    old = OrderItem.query.filter_by(visit_id=visit.id,kind='ticket',status='active').with_for_update().all()
    if len(old)!=1: raise ApiError('门票记录异常，请先核对账单',409,'TICKET_CONFLICT')
    before = order_item_dict(old[0])
    if old[0].catalog_item_id!=ticket.id:
        old[0].status='voided'; old[0].voided_by_id=employee.id
        old[0].void_reason='更改票种'; old[0].voided_at=datetime.now(timezone.utc); old[0].version+=1
        db.session.add(OrderItem(visit_id=visit.id,catalog_item_id=ticket.id,kind='ticket',name_snapshot=ticket.name,
            unit_price=ticket.price,quantity=1,total_amount=ticket.price,created_by_id=employee.id))
        visit.version+=1
    db.session.flush()
    items=OrderItem.query.filter_by(visit_id=visit.id).order_by(OrderItem.created_at,OrderItem.id).all()
    recompute_visit_billing(db.session,visit)
    payload=visit_dict(visit,db.session.get(Wristband,visit.wristband_id),items)
    write_audit('visit.ticket_change','visit',visit.id,{'before':before,'ticket_catalog_item_id':ticket.id,'after':payload})
    idempotency_store(idempotency_record_key(endpoint,employee.id,raw_key),endpoint,200,{'data':payload})
    db.session.commit()
    emit_business_event('visit.changed',{'visit_id':visit.id,'reason':'ticket_changed'})
    emit_business_event('wristbands.changed',{'wristband_id':visit.wristband_id})
    return success(payload,'票种已更改')


def _quantity(value) -> Decimal:
    return decimal_value(value, "数量", scale=3, positive=True)


def _load_visit(visit_id, lock=False):
    query = Visit.query.filter_by(id=visit_id)
    if lock:
        query = query.with_for_update()
    visit = query.first()
    if not visit:
        raise ApiError("账单不存在", 404, "NOT_FOUND")
    return visit


def _validate_catalog_quantity(catalog, quantity):
    if catalog.kind=='package' and quantity!=1:
        raise ApiError('每张手牌只能选择一份套票',400,'INVALID_PACKAGE')
    if catalog.kind == "service" and quantity != quantity.to_integral_value():
        raise ApiError("服务数量必须为整数")


def _validate_visit_version(visit, body):
    if 'version' in body and (type(body['version']) is not int or body['version'] != visit.version):
        raise ApiError("手牌消费已更新，请核对后重新提交", 409, "VISIT_VERSION_CONFLICT")


def _create_order_item(visit, catalog, quantity, employee, service_employee_id=None, selection=None, masters=None, legacy=True):
    total = decimal_value((Decimal(catalog.price) * quantity).quantize(Decimal("0.01")), "消费金额")
    item = OrderItem(
        visit_id=visit.id,
        catalog_item_id=catalog.id,
        kind=catalog.kind,
        name_snapshot=catalog.name,
        unit_price=catalog.price,
        quantity=quantity,
        total_amount=total,
        service_employee_id=service_employee_id or None,
        created_by_id=employee.id,
        inventory_mode='legacy' if legacy else 'manual',
    )
    db.session.add(item)
    db.session.flush()
    consume_order(item, selection or [], masters or {}, employee, legacy=legacy)
    write_audit(
        "visit.item_add",
        "order_item",
        item.id,
        {"visit_id": visit.id, "item": order_item_dict(item)},
    )
    return item


def _create_order_selection(visit,normalized,catalog_by_id,employee,body):
    selected=[row for row in normalized if catalog_by_id[row['catalog_item_id']].kind=='package']
    if len(selected)>1: raise ApiError('一次只能选择一个套票',400,'INVALID_PACKAGE')
    if 'confirm_replace' in body and type(body['confirm_replace']) is not bool:
        raise ApiError('套票替换确认无效',400,'INVALID_PACKAGE')
    if selected and not has_permission(employee,'visit:package'):
        raise ApiError('没有选取或更换套票的权限',403,'PERMISSION_DENIED')
    # Existing same-package selection is a no-op, never a second stock write.
    from ..models import OrderStockConsumption
    for row in normalized:
        if catalog_by_id[row['catalog_item_id']].kind != 'package': continue
        parent = OrderItem.query.filter_by(visit_id=visit.id,kind='package',status='active',
            catalog_item_id=row['catalog_item_id']).with_for_update().first()
        if parent:
            if row.get('inventory_consumption') is not None:
                original = {r.stock_item_id:r.quantity for r in OrderStockConsumption.query.filter_by(order_item_id=parent.id).all()}
                requested = {r['stock_item_id']:r['quantity'] for r in row['inventory_consumption']}
                if requested != original:
                    raise ApiError('套票已在账单中，请先取消后重新选择耗材',409,'PACKAGE_CONSUMPTION_CONFLICT')
            row['inventory_consumption']=[]
            row['_existing_package']=True
    recorded_returns = {}
    if selected and body.get('confirm_replace') and not selected[0].get('_existing_package'):
        previous = OrderItem.query.filter_by(visit_id=visit.id,kind='package',status='active').with_for_update().all()
        if len(previous)>1: raise ApiError('账单存在重复套票，请先核对',409,'PACKAGE_CONFLICT')
        if previous:
            for record in OrderStockConsumption.query.filter_by(order_item_id=previous[0].id).all():
                recorded_returns[record.stock_item_id] = recorded_returns.get(record.stock_item_id,Decimal(0)) + record.quantity
    masters = prepare_consumption(normalized, catalog_by_id,recorded_returns=recorded_returns)
    result=[]
    if selected:
        result.append(set_visit_package(db.session,visit,catalog_by_id[selected[0]['catalog_item_id']],
            employee,confirm_replace=body.get('confirm_replace',False),defer_billing=True))
    for row in normalized:
        catalog=catalog_by_id[row['catalog_item_id']]
        if catalog.kind!='package':
            result.append(_create_order_item(visit,catalog,row['quantity'],employee,row.get('service_employee_id'),
                row['inventory_consumption'], masters, row['_legacy_consumption']))
        elif not row.get('_existing_package') and not row['_legacy_consumption']:
            consume_order(result[0], row['inventory_consumption'], masters, employee, legacy=False)
            result[0].inventory_mode = 'manual'
    recompute_visit_billing(db.session,visit)
    return result


@bp.get("/<visit_id>")
@require_permission("visit:read")
def get_visit(visit_id):
    employee = current_employee()
    visit = _load_visit(visit_id)
    require_order_target(employee, db.session.get(Wristband, visit.wristband_id), visit)
    linked_visits = [visit]
    if visit.party_id and visit.status in {"open", "settling"}:
        linked_visits = (
            Visit.query.filter(
                Visit.party_id == visit.party_id,
                Visit.status.in_(["open", "settling"]),
            )
            .order_by(Visit.opened_at)
            .all()
        )
    linked_payloads = []
    linked_total = Decimal("0.00")
    current_payload = None
    for linked_visit in linked_visits:
        wristband = db.session.get(Wristband, linked_visit.wristband_id)
        if not can_read_visit(employee, wristband, linked_visit):
            continue
        items = OrderItem.query.filter_by(visit_id=linked_visit.id).order_by(OrderItem.created_at).all()
        payload = visit_dict(linked_visit, wristband, items)
        linked_payloads.append(payload)
        linked_total += Decimal(payload["total_amount"])
        if linked_visit.id == visit.id:
            current_payload = dict(payload)
    current_payload = current_payload or dict(linked_payloads[0])
    current_payload["linked_visits"] = linked_payloads
    current_payload["linked_total_amount"] = str(linked_total.quantize(Decimal("0.01")))
    return success(current_payload)


@bp.post("/<visit_id>/items")
@require_permission("visit:order")
@serialized_financial_write
def add_item(visit_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    visit = _load_visit(visit_id, lock=True)
    require_order_target(employee, db.session.get(Wristband, visit.wristband_id), visit)
    raw_key = str(request.headers.get('Idempotency-Key') or body.get('idempotency_key') or '').strip()
    endpoint = f'visits:{visit_id}:items'
    existing = idempotency_lookup(endpoint, employee.id, raw_key) if raw_key else None
    if existing: return success(existing.response_body['data'], '已返回原加单结果', existing.response_status)
    selection = normalize_consumption(body)
    if selection is not None and not raw_key:
        raise ApiError('缺少幂等请求编号',400,'IDEMPOTENCY_REQUIRED')
    _validate_visit_version(visit, body)
    if visit.status != "open":
        raise ApiError("当前账单不能加项", 409, "VISIT_NOT_OPEN")
    catalog = CatalogItem.query.with_for_update().filter_by(id=body.get("catalog_item_id"), is_active=True).first()
    if not catalog or catalog.kind not in {"service", "product"}:
        raise ApiError("消费项目不存在或已停用", 404, "ITEM_NOT_AVAILABLE")
    require_order_catalog(employee, catalog)
    quantity = _quantity(body.get("quantity", 1))
    _validate_catalog_quantity(catalog, quantity)
    normalized = [{'catalog_item_id':catalog.id, 'quantity':quantity, 'inventory_consumption':selection}]
    masters = prepare_consumption(normalized, {catalog.id:catalog})
    item = _create_order_item(
        visit,
        catalog,
        quantity,
        employee,
        body.get("service_employee_id"),
        normalized[0]['inventory_consumption'], masters, normalized[0]['_legacy_consumption'],
    )
    recompute_visit_billing(db.session,visit)
    visit.version += 1
    payload = order_item_dict(item)
    if raw_key: idempotency_store(idempotency_record_key(endpoint, employee.id, raw_key), endpoint, 201, {'data':payload})
    db.session.commit()
    emit_business_event("visit.changed", {"visit_id": visit.id})
    emit_business_event("inventory.changed", {"catalog_item_id": catalog.id})
    return success(payload, "加单成功", 201)


@bp.post("/<visit_id>/items/batch")
@require_permission("visit:order")
@serialized_financial_write
def add_items_batch(visit_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    raw_key = str(request.headers.get("Idempotency-Key") or body.get("idempotency_key") or "").strip()
    if not raw_key:
        raise ApiError("缺少幂等请求编号", 400, "IDEMPOTENCY_REQUIRED")
    endpoint = f"visits:{visit_id}:items:batch"
    visit = _load_visit(visit_id, lock=True)
    require_order_target(employee, db.session.get(Wristband, visit.wristband_id), visit)
    existing = idempotency_lookup(endpoint, employee.id, raw_key)
    if existing:
        return success(
            existing.response_body["data"],
            "已返回原加单结果",
            existing.response_status,
        )
    _validate_visit_version(visit, body)
    requested_items = body.get("items")
    if not isinstance(requested_items, list) or not requested_items:
        raise ApiError("请选择至少一个项目")
    if len(requested_items) > 50:
        raise ApiError("一次最多可添加 50 个项目")

    normalized = []
    for row in requested_items:
        if not isinstance(row, dict) or not row.get("catalog_item_id"):
            raise ApiError("加单项目格式错误")
        if set(row)-{'catalog_item_id','quantity','service_employee_id','inventory_mode','inventory_consumption'}:
            raise ApiError('加单不接受客户端金额或包含额度',400,'INVALID_ORDER')
        normalized.append(
            {
                "catalog_item_id": str(row["catalog_item_id"]),
                "quantity": _quantity(row.get("quantity", 1)),
                "service_employee_id": row.get("service_employee_id") or None,
                "inventory_consumption": normalize_consumption(row),
            }
        )

    if visit.status != "open":
        raise ApiError("当前账单不能加项", 409, "VISIT_NOT_OPEN")

    catalog_ids = sorted({row["catalog_item_id"] for row in normalized})
    catalogs = (
        CatalogItem.query.with_for_update()
        .filter(CatalogItem.id.in_(catalog_ids), CatalogItem.is_active.is_(True))
        .order_by(CatalogItem.id)
        .all()
    )
    catalog_by_id = {row.id: row for row in catalogs}
    if len(catalog_by_id) != len(catalog_ids):
        raise ApiError("部分消费项目不存在或已停用", 404, "ITEM_NOT_AVAILABLE")

    required_stock = {}
    for row in normalized:
        catalog = catalog_by_id[row["catalog_item_id"]]
        if catalog.kind not in {"service", "product", "package"}:
            raise ApiError("消费项目不存在或已停用", 404, "ITEM_NOT_AVAILABLE")
        require_order_catalog(employee, catalog)
        _validate_catalog_quantity(catalog, row["quantity"])
        if row['inventory_consumption'] is None and catalog.kind == "product" and catalog.stock_tracked:
            required_stock[catalog.id] = required_stock.get(catalog.id, Decimal("0")) + row["quantity"]
    items = _create_order_selection(visit,normalized,catalog_by_id,employee,body)
    visit.version += 1
    payload = [order_item_dict(item) for item in items]
    idempotency_store(
        idempotency_record_key(endpoint, employee.id, raw_key),
        endpoint,
        201,
        {"data": payload},
    )
    db.session.commit()
    emit_business_event("visit.changed", {"visit_id": visit.id})
    if required_stock or any(row['inventory_consumption'] for row in normalized):
        emit_business_event("inventory.changed", {"reason": "batch_sale"})
    return success(payload, f"成功添加 {len(items)} 个项目", 201)


@bp.post("/<visit_id>/items/<item_id>/void")
@require_permission("visit:write")
@serialized_financial_write
def void_item(visit_id, item_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    raw_key = str(request.headers.get("Idempotency-Key") or body.get("idempotency_key") or "").strip()
    if not raw_key:
        raise ApiError("缺少幂等请求编号", 400, "IDEMPOTENCY_REQUIRED")
    endpoint = f"visits:{visit_id}:items:{item_id}:void"
    existing = idempotency_lookup(endpoint, employee.id, raw_key)
    if existing:
        return success(
            existing.response_body["data"],
            "已返回原撤销结果",
            existing.response_status,
        )
    reason = str(body.get("reason", "")).strip() or "前台直接撤销"
    visit = _load_visit(visit_id, lock=True)
    require_order_target(employee, db.session.get(Wristband, visit.wristband_id), visit)
    if visit.status != "open":
        raise ApiError("当前账单不能撤销项目", 409, "VISIT_NOT_OPEN")
    item = OrderItem.query.with_for_update().filter_by(id=item_id, visit_id=visit.id).first()
    if not item or item.status != "active":
        raise ApiError("项目不存在或已撤销", 409, "ITEM_NOT_ACTIVE")
    if item.kind in {"ticket", "compensation"} and not has_permission(employee, "checkout:refund"):
        raise ApiError("撤销门票或赔偿需要经理权限", 403, "FORBIDDEN")
    before = order_item_dict(item)
    if item.kind=='package':
        if not has_permission(employee,'visit:package'):
            raise ApiError('没有取消套票的权限',403,'PERMISSION_DENIED')
        cancel_visit_package(db.session,visit,employee)
    item.status = "voided"
    item.covered_quantity=Decimal(0)
    item.package_order_item_id=None
    item.void_reason = reason
    item.voided_by_id = employee.id
    item.voided_at = datetime.now(timezone.utc)
    item.version += 1
    if item.kind != 'package':
        return_order_stock(item, employee, reason)
    recompute_visit_billing(db.session,visit)
    visit.version += 1
    write_audit(
        "visit.item_void",
        "order_item",
        item.id,
        {"visit_id": visit.id, "reason": reason, "before": before, "after": order_item_dict(item)},
    )
    payload = order_item_dict(item)
    idempotency_store(
        idempotency_record_key(endpoint, employee.id, raw_key),
        endpoint,
        200,
        {"data": payload},
    )
    db.session.commit()
    emit_business_event("visit.changed", {"visit_id": visit.id})
    emit_business_event("inventory.changed", {"reason": "void"})
    return success(payload, "项目已撤销")
