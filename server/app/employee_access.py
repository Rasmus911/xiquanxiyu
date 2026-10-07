"""Role templates constrain grants; only the active UUID policy binds administrators."""
from .api.errors import ApiError

DEFAULT_CHANNELS = {
    'cashier': ('desktop', 'web'),
    'inventory': ('desktop', 'web', 'mobile'),
    'male_scrubber': ('desktop', 'web', 'mobile'),
    'female_scrubber': ('desktop', 'web', 'mobile'),
    'floor_attendant': ('desktop', 'web', 'mobile'),
    'manager': ('desktop', 'web'),
}


def validate_employee_channels(role, channels):
    permitted = DEFAULT_CHANNELS.get(role)
    if (permitted is None or not isinstance(channels, list)
            or any(not isinstance(value, str) or value not in permitted for value in channels)
            or len(set(channels)) != len(channels)):
        raise ApiError('入口授权不符合该岗位，请重新选择', 400, 'INVALID_EMPLOYEE_CHANNELS')
    return [channel for channel in permitted if channel in channels]


def is_protected_employee(employee):
    from .access_policy import active_policy, policy_enforced
    from .models import AccessPolicyModel

    if not employee:
        return False
    if not policy_enforced():
        return employee.role == 'admin'
    # Read-only bootstrap/maintenance previews must still work before activation.
    if not AccessPolicyModel.query.filter_by(is_active=True).first():
        return False
    policy = active_policy()
    return employee.id in {policy.owner_id, *policy.mobile_employee_ids, *policy.administrator_employee_ids}


def session_ui(employee, channel, permissions):
    def permits(permission):
        return '*' in permissions or permission in permissions

    mobile = channel == 'mobile'
    caps = {
        'visit_clear': not mobile and permits('visit:clear'),
        'member_delete': not mobile and permits('member:delete'),
        'catalog_delete': not mobile and permits('catalog:delete'),
        'catalog_write': not mobile and permits('catalog:write'),
        'visit_open': not mobile and permits('visit:write'),
        'visit_manage': not mobile and permits('visit:write'),
        'visit_order': permits('visit:order') or (mobile and permits('mobile:order')),
        'checkout_write': not mobile and permits('checkout:write'),
        'member_write': not mobile and permits('member:write'),
        'receipt_reprint': not mobile and permits('print:write'),
        'inventory_write': permits('inventory:write'),
        'catalog_layout': permits('catalog:layout'),
        'package_write': permits('visit:package'),
    }
    candidates = [('wristbands', 'mobile:order' if mobile else 'visit:read')]
    if not mobile:
        candidates += [('members', 'member:read'), ('print-jobs', 'print:write')]
        candidates.append(('catalog', 'catalog:write'))
    candidates += [('inventory', 'inventory:read'), ('reports', 'report:read')]
    if not mobile:
        candidates += [('audit', 'audit:read'), ('employees', 'employee:read'), ('settings', 'settings:read')]
    return {'ui_pages': [page for page, permission in candidates if permits(permission)], 'capabilities': caps}
