import re
import uuid
from decimal import Decimal

from flask import Blueprint, request

from ..access_policy import emit_business_event
from ..audit_service import write_audit
from ..auth_service import current_employee, require_permission, verify_sensitive_password
from ..extensions import db
from ..financial_lock import serialized_financial_write
from ..models import (
    AuditLog,
    CatalogItem,
    InventoryMovement,
    Member,
    OrderItem,
    SystemSetting,
    Visit,
    Wristband,
    utcnow,
)
from ..serializers import visit_dict, wristband_dict
from ..ordering_scope import can_read_visit, full_ordering
from .errors import ApiError, success

bp = Blueprint("wristbands", __name__, url_prefix="/wristbands")
ACTIVE_VISIT_STATUSES = ["open", "settling"]


def _active_visit(wristband_id, lock=False):
    query = Visit.query.filter(Visit.wristband_id == wristband_id, Visit.status.in_(ACTIVE_VISIT_STATUSES))
    if lock:
        query = query.with_for_update()
    return query.first()


def _visit_amount(visit_id):
    rows = OrderItem.query.filter_by(visit_id=visit_id, status="active").all()
    return sum((Decimal(row.total_amount) for row in rows), Decimal("0.00"))


def _active_ticket(ticket_id=None):
    if ticket_id is not None:
        ticket = CatalogItem.query.filter_by(id=ticket_id,kind='ticket',is_active=True).first()
        if not ticket or ticket.reference_code not in {'ticket.adult','ticket.child'}:
            raise ApiError('请选择有效的成人或儿童门票',400,'INVALID_TICKET')
        return ticket
    ticket = CatalogItem.query.filter_by(reference_code='ticket.adult',kind='ticket',is_active=True).first()
    if not ticket:
        # Historical explicit legacy fixtures / not-yet-cut-over databases only.
        ticket = CatalogItem.query.filter_by(kind='ticket',is_active=True,reference_code=None).order_by(
            CatalogItem.sort_order,CatalogItem.created_at).first()
    if not ticket:
        raise ApiError("未配置基础门票", 409, "TICKET_NOT_CONFIGURED")
    return ticket


def _current_number(value):
    value = str(value).strip()
    return value.zfill(3) if re.fullmatch(r'[0-9]{1,3}',value) and 1<=int(value)<=100 else value


def _require_current_band(wristband):
    if not wristband.is_active:
        raise ApiError('旧手牌已退役，请使用当前手牌',409,'WRISTBAND_RETIRED')


def _create_visit(wristband, employee, member_id=None, note=None, party_id=None, ticket_id=None):
    _require_current_band(wristband)
    if member_id and not Member.query.filter_by(id=member_id, is_active=True, deleted_at=None).with_for_update().first():
        raise ApiError('会员不存在或已归档', 404, 'NOT_FOUND')
    ticket = _active_ticket(ticket_id)
    visit = Visit(
        wristband_id=wristband.id,
        member_id=member_id or None,
        party_id=party_id,
        opened_by_id=employee.id,
        note=note or None,
    )
    db.session.add(visit)
    db.session.flush()
    ticket_item = OrderItem(
        visit_id=visit.id,
        catalog_item_id=ticket.id,
        kind="ticket",
        name_snapshot=ticket.name,
        unit_price=ticket.price,
        quantity=Decimal("1"),
        total_amount=ticket.price,
        created_by_id=employee.id,
    )
    db.session.add(ticket_item)
    wristband.status = "in_use"
    wristband.note = None
    wristband.version += 1
    return visit, ticket_item


@bp.get("")
@require_permission("visit:read")
def list_wristbands():
    employee = current_employee()
    status = request.args.get("status")
    keyword = _current_number(request.args.get("keyword", ""))
    query = Wristband.query.filter_by(is_active=True)
    if status:
        query = query.filter_by(status=status)
    if keyword:
        query = query.filter(Wristband.number.ilike(f"%{keyword}%"))
    wristbands = query.order_by(Wristband.number).all()
    wristband_ids = [row.id for row in wristbands]
    visits = (
        Visit.query.filter(Visit.wristband_id.in_(wristband_ids), Visit.status.in_(ACTIVE_VISIT_STATUSES)).all()
        if wristband_ids
        else []
    )
    visit_by_wristband = {row.wristband_id: row for row in visits}
    visit_ids = [row.id for row in visits]
    amounts = {visit_id: Decimal("0.00") for visit_id in visit_ids}
    if visit_ids:
        for row in OrderItem.query.filter(OrderItem.visit_id.in_(visit_ids), OrderItem.status == "active").all():
            amounts[row.visit_id] += Decimal(row.total_amount)

    all_active_visits = Visit.query.filter(Visit.status.in_(ACTIVE_VISIT_STATUSES)).all()
    all_band_ids = [row.wristband_id for row in all_active_visits]
    all_bands = (
        {row.id: row for row in Wristband.query.filter(Wristband.id.in_(all_band_ids)).all()}
        if all_band_ids
        else {}
    )
    band_numbers = {key: row.number for key, row in all_bands.items()}
    all_visit_ids = [row.id for row in all_active_visits]
    all_amounts = {visit_id: Decimal("0.00") for visit_id in all_visit_ids}
    if all_visit_ids:
        for row in OrderItem.query.filter(OrderItem.visit_id.in_(all_visit_ids), OrderItem.status == "active").all():
            all_amounts[row.visit_id] += Decimal(row.total_amount)
    parties = {}
    for active_visit in all_active_visits:
        if active_visit.party_id:
            parties.setdefault(active_visit.party_id, []).append(active_visit)

    items = []
    for wristband in wristbands:
        visit = visit_by_wristband.get(wristband.id)
        if not full_ordering(employee) and not can_read_visit(employee, wristband, visit):
            continue
        linked = parties.get(visit.party_id, [visit]) if visit else []
        linked = [row for row in linked if row and can_read_visit(employee, all_bands.get(row.wristband_id), row)]
        items.append(
            wristband_dict(
                wristband,
                visit,
                amounts.get(visit.id, Decimal("0.00")) if visit else Decimal("0.00"),
                [band_numbers.get(row.wristband_id, "") for row in linked],
                [row.id for row in linked],
                sum((all_amounts.get(row.id, Decimal("0.00")) for row in linked), Decimal("0.00")),
            )
        )
    return success(items)


@bp.post("/bulk")
@require_permission("*")
@serialized_financial_write
def bulk_create():
    body = request.get_json(silent=True) or {}
    numbers = body.get("numbers")
    if not isinstance(numbers, list):
        start = int(body.get("start", 0))
        end = int(body.get("end", 0))
        width = int(body.get("width", 3))
        if start <= 0 or end < start or end - start > 2000:
            raise ApiError("手牌号码范围无效")
        numbers = [str(number).zfill(width) for number in range(start, end + 1)]
    clean_numbers = sorted({_current_number(number) for number in numbers if str(number).strip()})
    existing = {row.number for row in Wristband.query.filter(Wristband.number.in_(clean_numbers)).all()}
    created = []
    for number in clean_numbers:
        if number not in existing:
            from ..serializers import wristband_area
            area = 'male' if number in {f'{n:03}' for n in range(1,51)} else (
                'female' if number in {f'{n:03}' for n in range(51,101)} else wristband_area(number))
            row = Wristband(number=number,bath_area=area)
            db.session.add(row)
            created.append(row)
    db.session.flush()
    write_audit(
        "wristband.bulk_create",
        "wristband",
        None,
        {"created": [row.number for row in created], "skipped": sorted(existing)},
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"reason": "bulk_create"})
    return success(
        {"created": [wristband_dict(row) for row in created], "skipped": sorted(existing)},
        "手牌创建完成",
        201,
    )


@bp.patch("/<wristband_id>")
@require_permission("*")
@serialized_financial_write
def update_wristband(wristband_id):
    row = db.session.get(Wristband, wristband_id)
    if not row:
        raise ApiError("手牌不存在", 404, "NOT_FOUND")
    _require_current_band(row)
    if _active_visit(row.id):
        raise ApiError("使用中的手牌不能停用或改号", 409, "WRISTBAND_IN_USE")
    body = request.get_json(silent=True) or {}
    before = wristband_dict(row)
    if "number" in body:
        row.number = str(body["number"]).strip()
    if "status" in body:
        if body["status"] not in {"available", "disabled", "lost"}:
            raise ApiError("手牌状态无效")
        row.status = body["status"]
    if "note" in body:
        row.note = str(body["note"]).strip() or None
    row.version += 1
    write_audit(
        "wristband.update",
        "wristband",
        row.id,
        {"before": before, "after": wristband_dict(row)},
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"wristband_id": row.id})
    return success(wristband_dict(row))


@bp.post("/<wristband_id>/open")
@require_permission("visit:write")
@serialized_financial_write
def open_visit(wristband_id):
    employee = current_employee()
    wristband = Wristband.query.with_for_update().filter_by(id=wristband_id).first()
    if not wristband:
        raise ApiError("手牌不存在", 404, "NOT_FOUND")
    _require_current_band(wristband)
    if wristband.status != "available" or _active_visit(wristband.id, lock=True):
        raise ApiError("手牌当前不可开单", 409, "WRISTBAND_UNAVAILABLE")
    body = request.get_json(silent=True) or {}
    if set(body)-{'member_id','note','ticket_catalog_item_id'}:
        raise ApiError('开牌仅接受会员、备注与服务器票种，不接受客户端金额')
    if 'ticket_catalog_item_id' in body and not isinstance(body['ticket_catalog_item_id'],str):
        raise ApiError('请选择有效门票',400,'INVALID_TICKET')
    visit, ticket_item = _create_visit(
        wristband,
        employee,
        body.get("member_id"),
        str(body.get("note", "")).strip(),
        ticket_id=body.get('ticket_catalog_item_id'),
    )
    write_audit(
        "visit.open",
        "visit",
        visit.id,
        {"wristband_number": wristband.number, "ticket_price": str(ticket_item.unit_price)},
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"wristband_id": wristband.id})
    return success(visit_dict(visit, wristband, [ticket_item]), "开单成功", 201)


def _link_selected_wristbands(wristbands, employee, ticket_ids=None):
    if len(wristbands) < 2:
        raise ApiError("请至少选择两个手牌")
    selected_visits = []
    auto_opened = []
    ticket_ids = ticket_ids or {}
    if (not isinstance(ticket_ids,dict) or set(ticket_ids)-{row.id for row in wristbands}
            or any(not isinstance(value,str) or not value for value in ticket_ids.values())):
        raise ApiError('逐人票种选择格式错误',400,'INVALID_TICKET')
    for wristband in wristbands:
        _require_current_band(wristband)
        visit = _active_visit(wristband.id, lock=True)
        if wristband.status == "available" and not visit:
            visit, _ticket_item = _create_visit(wristband, employee,ticket_id=ticket_ids.get(wristband.id))
            auto_opened.append(wristband.number)
        elif wristband.status != "in_use" or not visit:
            raise ApiError(f"{wristband.number} 号手牌当前不可联动", 409, "TARGET_UNAVAILABLE")
        selected_visits.append(visit)

    existing_party_ids = {row.party_id for row in selected_visits if row.party_id}
    group_visits = list(selected_visits)
    if existing_party_ids:
        group_visits.extend(
            Visit.query.filter(Visit.party_id.in_(existing_party_ids), Visit.status.in_(ACTIVE_VISIT_STATUSES)).all()
        )
    unique_visits = {row.id: row for row in group_visits}
    party_id = next(iter(existing_party_ids), None) or str(uuid.uuid4())
    for visit in unique_visits.values():
        visit.party_id = party_id
        visit.version += 1

    linked_wristbands = Wristband.query.filter(
        Wristband.id.in_([row.wristband_id for row in unique_visits.values()])
    ).all()
    linked_numbers = sorted(row.number for row in linked_wristbands)
    write_audit(
        "wristband.link",
        "visit",
        selected_visits[0].id,
        {
            "party_id": party_id,
            "linked_wristbands": linked_numbers,
            "auto_opened": auto_opened,
        },
    )
    return {
        "party_id": party_id,
        "linked_wristbands": linked_numbers,
        "visit_ids": sorted(unique_visits),
        "auto_opened": auto_opened,
    }


@bp.post("/link-batch")
@require_permission("visit:write")
@serialized_financial_write
def link_wristbands_batch():
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    wristband_ids = sorted({str(value) for value in body.get("wristband_ids", []) if value})
    if len(wristband_ids) < 2:
        raise ApiError("请至少选择两个手牌")
    if len(wristband_ids) > 20:
        raise ApiError("一次最多联动 20 个手牌")
    wristbands = (
        Wristband.query.filter(Wristband.id.in_(wristband_ids)).order_by(Wristband.number).with_for_update().all()
    )
    if len(wristbands) != len(wristband_ids):
        raise ApiError("部分手牌不存在，请刷新后重试", 409, "WRISTBAND_CHANGED")
    result = _link_selected_wristbands(wristbands, employee,body.get('ticket_catalog_item_ids'))
    db.session.commit()
    emit_business_event("wristbands.changed", {"reason": "link", "party_id": result["party_id"]})
    return success(result, "手牌批量联动成功")


@bp.post("/<wristband_id>/link")
@require_permission("visit:write")
@serialized_financial_write
def link_wristbands(wristband_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    raw_numbers = body.get("target_numbers") or body.get("target_number") or ""
    if isinstance(raw_numbers, list):
        target_numbers = {_current_number(number) for number in raw_numbers if str(number).strip()}
    else:
        target_numbers = {_current_number(number) for number in re.split(r"[,，、\s]+", str(raw_numbers).strip()) if number}
    source = Wristband.query.with_for_update().filter_by(id=wristband_id).first()
    if not source:
        raise ApiError("手牌不存在", 404, "NOT_FOUND")
    target_numbers.discard(source.number)
    targets = (
        Wristband.query.filter(Wristband.number.in_(sorted(target_numbers)))
        .order_by(Wristband.number)
        .with_for_update()
        .all()
    )
    if len(targets) != len(target_numbers):
        found = {row.number for row in targets}
        raise ApiError(f"手牌不存在：{', '.join(sorted(target_numbers - found))}")
    result = _link_selected_wristbands([source, *targets], employee)
    db.session.commit()
    emit_business_event("wristbands.changed", {"reason": "link", "party_id": result["party_id"]})
    return success(result, "手牌联动成功")


@bp.post("/<wristband_id>/force-clear")
@require_permission("visit:clear")
@serialized_financial_write
def force_clear_wristband(wristband_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    verify_sensitive_password(employee, body.get("password"))
    reason = str(body.get("reason", "")).strip()
    if not reason or len(reason) > 255:
        raise ApiError("清空账单必须填写原因，最多 255 字")

    wristband = Wristband.query.with_for_update().filter_by(id=wristband_id).first()
    if not wristband:
        raise ApiError("手牌不存在", 404, "NOT_FOUND")
    visit = _active_visit(wristband.id, lock=True)
    cleared_amount = Decimal("0.00")
    returned_products = []
    cleared_items = []
    if visit:
        active_items = OrderItem.query.with_for_update().filter_by(visit_id=visit.id, status="active").all()
        # Release package child references while the parent is still active.
        for item in active_items:
            item.covered_quantity = Decimal(0)
            item.package_order_item_id = None
        db.session.flush()
        for item in active_items:
            cleared_items.append(
                {
                    "id": item.id,
                    "name": item.name_snapshot,
                    "quantity": str(item.quantity),
                    "unit_price": str(item.unit_price),
                    "total_amount": str(item.total_amount),
                    "created_by_id": item.created_by_id,
                }
            )
            cleared_amount += Decimal(item.total_amount)
            item.status = "voided"
            item.void_reason = reason
            item.voided_by_id = employee.id
            item.voided_at = utcnow()
            item.version += 1
            from ..stock_service import return_order_stock
            return_order_stock(item, employee, reason, movement_type='force_clear_return')
            if item.kind == 'product': returned_products.append(item.name_snapshot)
        visit.status = "cancelled"
        visit.closed_at = utcnow()
        visit.party_id = None
        visit.note = reason
        visit.version += 1

    previous_status = wristband.status
    wristband.status = "available"
    wristband.note = None
    wristband.version += 1
    write_audit(
        "wristband.force_clear",
        "wristband",
        wristband.id,
        {
            "wristband_number": wristband.number,
            "previous_status": previous_status,
            "visit_id": visit.id if visit else None,
            "cleared_amount": str(cleared_amount),
            "returned_products": returned_products,
            "reason": reason,
            "authorization": "personal_password",
            "before": {"status": previous_status, "items": cleared_items, "amount": str(cleared_amount)},
            "after": {"status": wristband.status, "visit_status": visit.status if visit else None, "amount": "0.00"},
        },
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"reason": "force_clear", "wristband_id": wristband.id})
    emit_business_event("inventory.changed", {"reason": "force_clear"})
    return success(
        {
            "wristband": wristband_dict(wristband),
            "cancelled_visit_id": visit.id if visit else None,
            "cleared_amount": str(cleared_amount),
        },
        "手牌已强制清空并恢复为空闲",
    )


@bp.post("/<wristband_id>/switch")
@require_permission("visit:write")
@serialized_financial_write
def switch_wristband(wristband_id):
    body = request.get_json(silent=True) or {}
    target_number = _current_number(body.get("target_number", ""))
    source = Wristband.query.with_for_update().filter_by(id=wristband_id).first()
    target = Wristband.query.with_for_update().filter_by(number=target_number).first()
    if not source or not target:
        raise ApiError("原手牌或目标手牌不存在", 404, "NOT_FOUND")
    _require_current_band(source); _require_current_band(target)
    visit = _active_visit(source.id, lock=True)
    if not visit or source.status != "in_use":
        raise ApiError("原手牌没有活动账单", 409, "NO_ACTIVE_VISIT")
    if target.status != "available" or _active_visit(target.id, lock=True):
        raise ApiError("目标手牌不可用", 409, "TARGET_UNAVAILABLE")
    visit.wristband_id = target.id
    visit.version += 1
    source.status = "available"
    source.version += 1
    target.status = "in_use"
    target.version += 1
    write_audit(
        "wristband.switch",
        "visit",
        visit.id,
        {"from": source.number, "to": target.number},
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"reason": "switch"})
    return success({"visit_id": visit.id, "wristband": wristband_dict(target, visit)})


@bp.post("/<wristband_id>/lost")
@require_permission("visit:write")
@serialized_financial_write
def mark_lost(wristband_id):
    employee = current_employee()
    body = request.get_json(silent=True) or {}
    reason = str(body.get("reason", "")).strip()
    if not reason:
        raise ApiError("必须填写挂失原因")
    wristband = Wristband.query.with_for_update().filter_by(id=wristband_id).first()
    if not wristband:
        raise ApiError("手牌不存在", 404, "NOT_FOUND")
    visit = _active_visit(wristband.id, lock=True)
    if wristband.status != "in_use" or not visit:
        raise ApiError("只有使用中的手牌可以挂失", 409, "NOT_IN_USE")
    already_charged = OrderItem.query.filter_by(visit_id=visit.id, kind="compensation", status="active").first()
    if already_charged:
        raise ApiError("该账单已经收取挂失赔偿", 409, "ALREADY_LOST")
    setting = SystemSetting.query.filter_by(key="lost_wristband_fee").first()
    fee = Decimal(str(setting.value if setting else "20.00"))
    item = OrderItem(
        visit_id=visit.id,
        kind="compensation",
        name_snapshot="手牌挂失赔偿",
        unit_price=fee,
        quantity=Decimal("1"),
        total_amount=fee,
        created_by_id=employee.id,
    )
    db.session.add(item)
    wristband.status = "lost"
    wristband.note = reason
    wristband.version += 1
    write_audit(
        "wristband.lost",
        "visit",
        visit.id,
        {"wristband_number": wristband.number, "reason": reason, "fee": str(fee)},
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"wristband_id": wristband.id})
    return success({"visit_id": visit.id, "fee": str(fee)}, "挂失成功")


def _lost_visit_from_audit(wristband):
    rows = (
        AuditLog.query.filter_by(action="wristband.lost", entity_type="visit")
        .order_by(AuditLog.chain_index.desc())
        .limit(200)
        .all()
    )
    for row in rows:
        if row.details.get("wristband_number") != wristband.number:
            continue
        visit = Visit.query.with_for_update().filter_by(id=row.entity_id, status="open").first()
        if visit:
            return visit
    return None


@bp.post("/<wristband_id>/recover")
@require_permission("visit:write")
@serialized_financial_write
def recover_lost_wristband(wristband_id):
    employee = current_employee()
    wristband = Wristband.query.with_for_update().filter_by(id=wristband_id).first()
    if not wristband:
        raise ApiError("手牌不存在", 404, "NOT_FOUND")
    _require_current_band(wristband)
    if wristband.status != "lost":
        raise ApiError("只有已挂失手牌可以恢复", 409, "NOT_LOST")

    visit = _active_visit(wristband.id, lock=True) or _lost_visit_from_audit(wristband)
    compensation_items = []
    if visit:
        compensation_items = (
            OrderItem.query.with_for_update().filter_by(visit_id=visit.id, kind="compensation", status="active").all()
        )
        for item in compensation_items:
            item.status = "voided"
            item.void_reason = "挂失手牌已恢复"
            item.voided_by_id = employee.id
            item.voided_at = utcnow()
            item.version += 1
        visit.version += 1

    is_original_active_band = bool(visit and visit.wristband_id == wristband.id)
    wristband.status = "in_use" if is_original_active_band else "available"
    wristband.note = None
    wristband.version += 1
    removed_fee = sum((Decimal(item.total_amount) for item in compensation_items), Decimal("0.00"))
    write_audit(
        "wristband.recover",
        "wristband",
        wristband.id,
        {
            "wristband_number": wristband.number,
            "visit_id": visit.id if visit else None,
            "removed_compensation": str(removed_fee),
            "restored_status": wristband.status,
        },
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"wristband_id": wristband.id, "reason": "recover"})
    if visit:
        emit_business_event("visit.changed", {"visit_id": visit.id, "reason": "lost_recovered"})
    return success(
        {
            "wristband": wristband_dict(wristband, visit if is_original_active_band else None),
            "visit_id": visit.id if visit else None,
            "removed_compensation": str(removed_fee),
        },
        "手牌已恢复",
    )


@bp.post("/<wristband_id>/replace")
@require_permission("visit:write")
@serialized_financial_write
def replace_lost_wristband(wristband_id):
    body = request.get_json(silent=True) or {}
    target_number = _current_number(body.get("target_number", ""))
    source = Wristband.query.with_for_update().filter_by(id=wristband_id).first()
    target = Wristband.query.with_for_update().filter_by(number=target_number).first()
    if not source or not target:
        raise ApiError("手牌不存在", 404, "NOT_FOUND")
    _require_current_band(source); _require_current_band(target)
    visit = _active_visit(source.id, lock=True)
    if source.status != "lost" or not visit:
        raise ApiError("原手牌不是已挂失的活动手牌", 409, "NOT_LOST")
    if target.status != "available" or _active_visit(target.id, lock=True):
        raise ApiError("补发手牌不可用", 409, "TARGET_UNAVAILABLE")
    visit.wristband_id = target.id
    visit.version += 1
    target.status = "in_use"
    target.version += 1
    write_audit(
        "wristband.replace",
        "visit",
        visit.id,
        {"lost_wristband": source.number, "replacement": target.number},
    )
    db.session.commit()
    emit_business_event("wristbands.changed", {"reason": "replace"})
    return success({"visit_id": visit.id, "wristband": wristband_dict(target, visit)})
