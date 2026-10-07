"""Audited package application. Callers own the commit and request permissions."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from .api.errors import ApiError
from .audit_service import write_audit
from .financial_lock import serialize_financial_session
from .models import CatalogItem, OrderItem
from .package_billing import BillingLine, PackageSlot, allocate_inclusions, line_net_total
from .serializers import order_item_dict
from .validation import decimal_value

ZERO = Decimal('0')


def validate_package_definition(session, definition):
    if (not isinstance(definition, dict) or set(definition)-{'schema','slots','display_contents'}
            or type(definition.get('schema')) is not int or definition['schema'] != 1):
        raise ApiError('套票包含定义无效',400,'INVALID_PACKAGE')
    contents=definition.get('display_contents')
    slots=definition.get('slots')
    if (not isinstance(contents,list) or not contents or len(contents)>50
            or any(not isinstance(text,str) or not text.strip() or len(text)>200 for text in contents)
            or not isinstance(slots,list) or not 1<=len(slots)<=50):
        raise ApiError('套票内容和包含项目不能为空',400,'INVALID_PACKAGE')
    parsed=[]
    try:
        for slot in slots:
            if not isinstance(slot,dict) or set(slot)!={'catalog_item_ids','quantity'}:
                raise ValueError
            ids=slot['catalog_item_ids']
            if not isinstance(ids,list) or not 1<=len(ids)<=50 or not isinstance(slot['quantity'],str):
                raise ValueError
            parsed.append(PackageSlot(tuple(ids),decimal_value(slot['quantity'],'套票包含数量',scale=3,positive=True)))
        allocate_inclusions([],parsed)
    except (ValueError,TypeError,ArithmeticError):
        raise ApiError('套票包含额度无效',400,'INVALID_PACKAGE') from None
    ids={id_ for slot in parsed for id_ in slot.catalog_item_ids}
    rows=session.query(CatalogItem).filter(CatalogItem.id.in_(ids)).all()
    if len(rows)!=len(ids) or any(row.deleted_at or row.kind not in {'ticket','service','product'} for row in rows):
        raise ApiError('套票引用的项目不存在或类型不正确',400,'INVALID_PACKAGE')
    tickets={row.id for row in rows if row.kind=='ticket'}
    ticket_slots=[slot for slot in parsed if tickets.intersection(slot.catalog_item_ids)]
    if (len(ticket_slots)!=1 or ticket_slots[0].quantity!=Decimal(1)
            or not set(ticket_slots[0].catalog_item_ids)<=tickets):
        raise ApiError('套票须包含一个共享门票额度',400,'INVALID_PACKAGE')
    return parsed


def _rows(session,visit):
    if visit.status!='open':
        raise ApiError('当前账单不能更改套票',409,'VISIT_NOT_OPEN')
    return session.query(OrderItem).filter_by(visit_id=visit.id,status='active').order_by(
        OrderItem.created_at,OrderItem.id).with_for_update().all()


def _parent(rows):
    parents=[row for row in rows if row.kind=='package']
    if len(parents)>1:
        raise ApiError('账单存在重复套票，请先核对',409,'PACKAGE_CONFLICT')
    return parents[0] if parents else None


def recompute_visit_billing(session,visit):
    serialize_financial_session(session)
    rows=_rows(session,visit)
    parent=_parent(rows)
    slots=[]
    if parent:
        snapshot=parent.package_snapshot
        if not isinstance(snapshot,dict):
            raise ApiError('套票快照缺失，请先核对',409,'PACKAGE_CONFLICT')
        definition={key:value for key,value in snapshot.items() if key!='reference_code'}
        slots=validate_package_definition(session,definition)
    ordinary=[row for row in rows if row.kind!='package']
    # Legacy compensation without a catalog still has a stable synthetic identity.
    lines=[BillingLine(row.id,row.catalog_item_id or 'order:'+row.id,
        Decimal(row.quantity),Decimal(row.unit_price),index) for index,row in enumerate(ordinary)]
    coverage=allocate_inclusions(lines,slots)
    before=[order_item_dict(row) for row in rows]
    for row,line in zip(ordinary,lines):
        included=coverage[row.id]
        net=line_net_total(line,included)
        parent_id=parent.id if parent and included else None
        if (Decimal(row.covered_quantity or 0)!=included or Decimal(row.total_amount)!=net
                or row.package_order_item_id!=parent_id):
            row.covered_quantity=included; row.package_order_item_id=parent_id
            row.total_amount=net; row.version+=1
    if parent:
        if Decimal(parent.quantity)!=1 or parent.package_order_item_id or Decimal(parent.covered_quantity or 0):
            raise ApiError('套票订单数量或引用异常',409,'PACKAGE_CONFLICT')
        parent.total_amount=Decimal(parent.unit_price).quantize(Decimal('0.01'))
    after=[order_item_dict(row) for row in rows]
    if before!=after:
        write_audit('visit.package_recompute','visit',visit.id,{'before':before,'after':after},session=session)
    return {'before':before,'after':after}


def _cancel_parent(session,visit,parent,employee):
    # Clear even voided references while the old parent is active, before voiding it.
    children=session.query(OrderItem).filter_by(visit_id=visit.id,package_order_item_id=parent.id).with_for_update().all()
    for row in children:
        row.covered_quantity=ZERO; row.package_order_item_id=None
        row.total_amount=(Decimal(row.unit_price)*Decimal(row.quantity)).quantize(Decimal('0.01'))
        row.version+=1
    session.flush()
    parent.status='voided'; parent.voided_by_id=employee.id
    parent.void_reason='取消或更换套票'; parent.voided_at=datetime.now(timezone.utc); parent.version+=1
    from .stock_service import return_order_stock
    return_order_stock(parent,employee,parent.void_reason)
    session.flush()


def set_visit_package(session,visit,catalog,employee,*,confirm_replace=False,defer_billing=False):
    serialize_financial_session(session)
    if not catalog or catalog.deleted_at or not catalog.is_active or catalog.kind!='package':
        raise ApiError('套票不存在或已停用',404,'ITEM_NOT_AVAILABLE')
    validate_package_definition(session,catalog.package_definition)
    rows=_rows(session,visit); parent=_parent(rows)
    if parent and parent.catalog_item_id==catalog.id:
        if not defer_billing: recompute_visit_billing(session,visit)
        return parent
    if parent and not confirm_replace:
        raise ApiError('已有套票，请确认替换',409,'PACKAGE_REPLACE_CONFIRM_REQUIRED')
    before=[order_item_dict(row) for row in rows]
    if parent: _cancel_parent(session,visit,parent,employee)
    parent=OrderItem(visit_id=visit.id,catalog_item_id=catalog.id,kind='package',
        name_snapshot=catalog.name,unit_price=catalog.price,quantity=Decimal(1),covered_quantity=ZERO,
        total_amount=catalog.price,package_snapshot={'reference_code':catalog.reference_code,
            **deepcopy(catalog.package_definition)},created_by_id=employee.id)
    session.add(parent); session.flush()
    if not defer_billing: recompute_visit_billing(session,visit)
    write_audit('visit.package_set','visit',visit.id,{'before':before,
        'after':[order_item_dict(row) for row in _rows(session,visit)]},session=session)
    return parent


def cancel_visit_package(session,visit,employee):
    serialize_financial_session(session)
    rows=_rows(session,visit); parent=_parent(rows)
    if not parent: raise ApiError('当前账单没有套票',409,'PACKAGE_NOT_ACTIVE')
    before=[order_item_dict(row) for row in rows]
    _cancel_parent(session,visit,parent,employee)
    recompute_visit_billing(session,visit)
    write_audit('visit.package_cancel','visit',visit.id,{'before':before,
        'after':[order_item_dict(row) for row in _rows(session,visit)]},session=session)
