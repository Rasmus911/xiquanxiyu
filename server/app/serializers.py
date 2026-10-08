from datetime import datetime, timezone
from decimal import Decimal

from .models import (
    AuditLog,
    CatalogItem,
    Employee,
    Member,
    OrderItem,
    Payment,
    Settlement,
    Shift,
    Terminal,
    Visit,
    Wristband,
)

ACTION_LABELS = {
    "system.bootstrap": "初始化系统管理员",
    "auth.login": "员工登录",
    "auth.logout": "员工退出登录",
    "employee.create": "创建员工账号",
    "employee.update": "修改员工账号",
    "employee.delete": "删除员工账号",
    "terminal.update": "修改终端设置",
    "setting.update": "修改系统设置",
    "catalog.create": "新增项目或商品",
    "catalog.update": "修改项目或商品",
    "catalog.delete": "归档项目或商品",
    "member.delete": "归档会员",
    "catalog.layout": "调整加单项目排列",
    "wristband.bulk_create": "批量建立手牌",
    "wristband.update": "修改手牌",
    "visit.open": "发放手牌并开单",
    "wristband.switch": "更换手牌",
    "wristband.lost": "挂失手牌",
    "wristband.recover": "恢复挂失手牌",
    "wristband.replace": "补发手牌",
    "wristband.force_clear": "强制清空手牌",
    "wristband.link": "联动手牌",
    "visit.item_add": "添加消费项目",
    "mobile.order_create": "手机端点单",
    "visit.item_void": "撤销消费项目",
    "checkout.complete": "完成结账",
    "checkout.refund": "结算退款",
    "receipt.print": "打印或补打小票",
    "member.create": "新增会员",
    "member.recharge": "会员储值充值",
    "member.pass_issue": "发放会员次卡",
    "member.pass_consume": "核销会员次卡",
    "member.card_sms": "发送会员开卡短信",
    "inventory.adjust": "调整商品库存",
    "stock.create": "新增库存主档",
    "stock.update": "修改库存主档",
    "stock.archive": "归档库存主档",
    "stock.catalog_reactivate": "随商品启用恢复库存",
    "stock.opening": "录入期初库存",
    "stock.purchase": "库存采购入库",
    "stock.return": "库存退回入库",
    "stock.loss": "库存报损",
    "stock.adjust": "调整库存余额",
    "stock.cost": "补录或更正入库成本",
    "stock.sale": "消费扣减库存",
    "stock.void_return": "撤销消费返还库存",
    "stock.force_clear_return": "强制清牌返还库存",
    "stock.photo_import": "导入照片盘点",
    "stock.photo_count": "照片盘点调整",
    "security.request_denied": "操作被拒绝",
    "audit.export": "导出审计证据",
    "audit.finance_check": "核对资金账目",
}

ENTITY_LABELS = {
    "system": "系统",
    "employee": "员工",
    "terminal": "终端",
    "setting": "系统设置",
    "catalog_item": "项目商品",
    "wristband": "手牌",
    "visit": "消费账单",
    "order_item": "消费项目",
    "settlement": "结算单",
    "print_job": "打印任务",
    "member": "会员",
    "member_pass": "会员次卡",
    "inventory": "库存",
    "stock_item": "库存主档",
    "stock_movement": "库存流水",
    "stock_source": "库存盘点来源",
}


def decimal_str(value) -> str:
    return f"{Decimal(value or 0):.2f}"


def iso(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat() if value else None


def employee_dict(item: Employee, channel=None):
    from .employee_access import is_protected_employee
    from .employee_access import session_ui
    from .auth_service import ROLE_PERMISSIONS
    from flask_jwt_extended import get_jwt
    permissions = ROLE_PERMISSIONS.get(item.role, set())
    try:
        claims = get_jwt()
    except RuntimeError:
        claims = {}
    if claims.get('sub') == item.id:
        from .access_policy import effective_permissions
        channel = claims.get('client_channel')
        permissions = effective_permissions(item, claims)
    elif channel:
        from .access_policy import session_permissions
        permissions = session_permissions(item, channel)
    return {
        "id": item.id,
        "username": item.username,
        "display_name": item.display_name,
        "role": item.role,
        "mobile_full_access": item.mobile_full_access,
        "is_active": item.is_active,
        "allowed_channels": list(item.allowed_channels or []),
        "deleted_at": iso(item.deleted_at),
        "protected_account": is_protected_employee(item),
        "last_login_at": iso(item.last_login_at),
        **session_ui(item, channel, permissions),
    }


def terminal_dict(item: Terminal):
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "printer_name": item.printer_name,
        "is_active": item.is_active,
        "last_seen_at": iso(item.last_seen_at),
    }


def wristband_area(number: str) -> str:
    try:
        numeric = int(number)
    except (TypeError, ValueError):
        return "other"
    if 8001 <= numeric <= 8060:
        return "male"
    if 9001 <= numeric <= 9060:
        return "female"
    return "other"


def wristband_dict(
    item: Wristband,
    visit: Visit | None = None,
    amount=None,
    linked_numbers=None,
    linked_visit_ids=None,
    linked_total=None,
):
    return {
        "id": item.id,
        "number": item.number,
        "bath_area": getattr(item, 'bath_area', None) or wristband_area(item.number),
        "is_active": item.is_active,
        "status": item.status,
        "note": item.note,
        "visit_id": visit.id if visit else None,
        "opened_at": iso(visit.opened_at) if visit else None,
        "amount": decimal_str(amount),
        "party_id": visit.party_id if visit else None,
        "linked_numbers": linked_numbers or [],
        "linked_visit_ids": linked_visit_ids or [],
        "linked_total_amount": decimal_str(linked_total if linked_total is not None else amount),
        "version": item.version,
    }


def catalog_dict(item: CatalogItem, employee=None):
    from .auth_service import has_permission
    can_edit = bool(employee and not item.deleted_at and has_permission(employee, 'catalog:write'))
    return {
        "id": item.id,
        "kind": item.kind,
        "can_edit": can_edit,
        "category": item.category,
        "name": item.name,
        "mobile_scope": item.mobile_scope,
        "reference_code": item.reference_code,
        "package_definition": item.package_definition,
        "price": decimal_str(item.price),
        "is_active": item.is_active,
        "stock_tracked": item.stock_tracked,
        "stock_quantity": str(item.stock_quantity or 0),
        "low_stock_threshold": str(item.low_stock_threshold or 0),
        "sort_order": item.sort_order,
        "version": item.version,
    }


def order_item_dict(item: OrderItem):
    from .models import OrderStockConsumption
    consumption = OrderStockConsumption.query.filter_by(order_item_id=item.id).order_by(OrderStockConsumption.stock_item_id).all()
    return {
        "id": item.id,
        "visit_id": item.visit_id,
        "catalog_item_id": item.catalog_item_id,
        "kind": item.kind,
        "name": item.name_snapshot,
        "unit_price": decimal_str(item.unit_price),
        "quantity": str(item.quantity),
        "covered_quantity": str(item.covered_quantity or 0),
        "gross_amount": decimal_str(Decimal(item.unit_price) * Decimal(item.quantity)),
        "included_amount": decimal_str(Decimal(item.unit_price) * Decimal(item.covered_quantity or 0)),
        "package_order_item_id": item.package_order_item_id,
        "package_snapshot": item.package_snapshot,
        "total_amount": decimal_str(item.total_amount),
        "status": item.status,
        "service_employee_id": item.service_employee_id,
        "void_reason": item.void_reason,
        "created_at": iso(item.created_at),
        "inventory_consumption": [{"stock_item_id": row.stock_item_id, "name": row.stock_name_snapshot,
            "base_unit": row.base_unit_snapshot, "quantity": f'{row.quantity:.3f}'} for row in consumption],
        "inventory_mode": item.inventory_mode,
    }


def stock_item_dict(item):
    return {"id": item.id, "name": item.name, "category": item.category, "base_unit": item.base_unit,
        "package_unit": item.package_unit, "units_per_package": f'{item.units_per_package:.3f}',
        "package_spec": item.package_spec, "stock_quantity": f'{item.stock_quantity:.3f}',
        "low_stock_threshold": f'{item.low_stock_threshold:.3f}', "is_active": item.is_active,
        "version": item.version, "legacy_catalog_item_id": item.legacy_catalog_item_id,
        "unit_cost": f'{item.unit_cost:.2f}' if item.unit_cost is not None else None}


def stock_movement_dict(row):
    from .stock_cost_service import current_cost, cost_dict
    return {"id": row.id, "stock_item_id": row.stock_item_id, "movement_type": row.movement_type,
        "quantity": f'{row.quantity:.3f}', "balance_before": f'{row.balance_before:.3f}',
        "balance_after": f'{row.balance_after:.3f}', "input_quantity": f'{row.input_quantity:.3f}',
        "input_unit": row.input_unit, "conversion_factor": f'{row.conversion_factor:.3f}',
        "base_unit": row.base_unit_snapshot, "package_unit": row.package_unit_snapshot,
        "reference_type": row.reference_type, "reference_id": row.reference_id,
        "operator_id": row.operator_id, "reason": row.reason, "created_at": iso(row.created_at),
        "cost": cost_dict(current_cost(row.id), row)}


def member_dict(item: Member, include_phone=True):
    phone = item.phone if include_phone else f"{item.phone[:3]}****{item.phone[-4:]}"
    return {
        "id": item.id,
        "phone": phone,
        "name": item.name,
        "balance": decimal_str(item.balance),
        "is_active": item.is_active,
        "note": item.note,
        "version": item.version,
    }


def visit_dict(item: Visit, wristband=None, order_items=None):
    order_items = order_items or []
    total = sum(
        (Decimal(row.total_amount) for row in order_items if row.status == "active"),
        Decimal("0.00"),
    )
    return {
        "id": item.id,
        "wristband_id": item.wristband_id,
        "wristband_number": wristband.number if wristband else None,
        "member_id": item.member_id,
        "party_id": item.party_id,
        "status": item.status,
        "opened_at": iso(item.opened_at),
        "closed_at": iso(item.closed_at),
        "note": item.note,
        "version": item.version,
        "total_amount": decimal_str(total),
        "items": [order_item_dict(row) for row in order_items],
    }


def payment_dict(item: Payment):
    return {
        "id": item.id,
        "method": item.method,
        "amount": decimal_str(item.amount),
        "reference": item.reference,
        "kind": item.kind,
    }


def settlement_dict(item: Settlement, payments=None, visits=None):
    return {
        "id": item.id,
        "number": item.number,
        "status": item.status,
        "total_amount": decimal_str(item.total_amount),
        "paid_amount": decimal_str(item.paid_amount),
        "completed_at": iso(item.completed_at),
        "payments": [payment_dict(row) for row in (payments or [])],
        "visits": visits or [],
    }


def shift_dict(item: Shift):
    return {
        "id": item.id,
        "employee_id": item.employee_id,
        "terminal_id": item.terminal_id,
        "status": item.status,
        "opening_cash": decimal_str(item.opening_cash),
        "expected_cash": decimal_str(item.expected_cash),
        "actual_cash": decimal_str(item.actual_cash),
        "difference": decimal_str(item.difference),
        "opened_at": iso(item.opened_at),
        "closed_at": iso(item.closed_at),
        "close_note": item.close_note,
    }


def audit_dict(item: AuditLog, employee: Employee | None = None, terminal: Terminal | None = None):
    employee_username = (item.context or {}).get("employee_username") or (employee.username if employee else "系统")
    return {
        "id": item.id,
        "chain_index": item.chain_index,
        # 对外展示的员工 ID 就是登录用户名；数据库 UUID 仅作为内部关联键保留。
        "employee_id": employee_username,
        "employee_record_id": item.employee_id,
        "employee_username": employee_username,
        "terminal_id": item.terminal_id,
        "terminal_code": (item.context or {}).get("terminal_code") or (terminal.code if terminal else "系统"),
        "terminal_name": (item.context or {}).get("terminal_name") or (terminal.name if terminal else "系统"),
        "action": item.action,
        "action_label": ACTION_LABELS.get(item.action, item.action),
        "entity_type": item.entity_type,
        "entity_label": ENTITY_LABELS.get(item.entity_type, item.entity_type),
        "entity_id": item.entity_id,
        "details": item.details,
        "request_id": item.request_id,
        "current_hash": item.current_hash,
        "prev_hash": item.prev_hash,
        "context": item.context,
        "integrity_version": item.integrity_version,
        "created_at": iso(item.created_at),
    }
