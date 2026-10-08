"""The two named accounts must also be active protected administrators on mobile."""
from .api.errors import ApiError

REGISTRATION_VIEW_USERNAMES = frozenset(('18603346509', '18631459666'))


def can_view_registration_token(employee, channel) -> bool:
    if channel != 'mobile' or employee is None:
        return False
    from .access_policy import active_policy
    from .extensions import db
    from .models import Employee
    try:
        policy = active_policy()
    except ApiError:
        return False
    actual = db.session.get(Employee, employee.id, populate_existing=True)
    protected_ids = {policy.owner_id, *policy.mobile_employee_ids, *policy.administrator_employee_ids}
    return bool(actual and actual.is_active and not actual.deleted_at and actual.role == 'admin'
                and actual.username in REGISTRATION_VIEW_USERNAMES
                and actual.id in protected_ids)
