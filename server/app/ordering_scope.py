"""One object boundary for every ordering API, independent of client-supplied scope."""
from .api.errors import ApiError
from .serializers import wristband_area

STAFF_AREAS = {
    'male_scrubber': {'male'}, 'female_scrubber': {'female'},
    'floor_attendant': {'male', 'female'},
}
STAFF_CATALOG = {
    'male_scrubber': {'scrub', 'both'}, 'female_scrubber': {'scrub', 'both'},
    'floor_attendant': {'rest', 'both'},
}


def bath_area(wristband):
    return getattr(wristband, 'bath_area', None) or wristband_area(wristband.number)


def full_ordering(employee):
    if employee.role in {'cashier', 'inventory', 'manager'}:
        return True
    if employee.role != 'admin':
        return False
    from .access_policy import policy_enforced
    from .employee_access import is_protected_employee
    return not policy_enforced() or is_protected_employee(employee)


def can_read_visit(employee, wristband, visit):
    if not wristband or not visit:
        return False
    if full_ordering(employee):
        return True
    return (wristband.is_active and wristband.status in {'in_use', 'lost'} and visit.status in {'open', 'settling'}
            and bath_area(wristband) in STAFF_AREAS.get(employee.role, set()))


def can_sell_catalog(employee, catalog):
    if not catalog or catalog.deleted_at or not catalog.is_active or catalog.kind not in {'service', 'product', 'package'}:
        return False
    if full_ordering(employee):
        return True
    if catalog.kind == 'package':
        return False
    if catalog.mobile_scope not in {'frontdesk', 'scrub', 'rest', 'both'}:
        return False
    return catalog.mobile_scope in STAFF_CATALOG.get(employee.role, set())


def require_order_target(employee, wristband, visit):
    if (not can_read_visit(employee, wristband, visit)
            or (not full_ordering(employee) and (wristband.status != 'in_use' or visit.status != 'open'))):
        raise ApiError('无权访问该浴区的已激活手牌', 403, 'PERMISSION_DENIED')


def require_order_catalog(employee, catalog):
    if not can_sell_catalog(employee, catalog):
        raise ApiError('该岗位不能销售此服务或商品', 403, 'PERMISSION_DENIED')
