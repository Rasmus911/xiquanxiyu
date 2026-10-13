"""Non-authenticating, append-only responsibility for removed employee logins."""
from flask import has_request_context
from sqlalchemy import event, inspect, select

from .models import Employee, EmployeeIdentity

HISTORICAL_EMPLOYEE_REFERENCES = {
    'audit_logs': ('employee_id',), 'revoked_sessions': ('employee_id',),
    'visits': ('opened_by_id',),
    'order_items': ('service_employee_id', 'created_by_id', 'voided_by_id'),
    'shifts': ('employee_id',), 'settlements': ('created_by_id',),
    'stored_value_ledgers': ('operator_id',), 'pass_ledgers': ('operator_id',),
    'inventory_movements': ('operator_id',), 'stock_movements': ('operator_id',),
    'stock_costs': ('operator_id',), 'registration_receipts': ('employee_id',),
    'registration_token_views': ('employee_id',),
}


def ensure_employee_identity(connection, employee):
    table = EmployeeIdentity.__table__
    if connection.execute(select(table.c.id).where(table.c.id == employee.id)).first() is None:
        connection.execute(table.insert().values(id=employee.id, username=employee.username,
            display_name=employee.display_name, role=employee.role, created_at=employee.created_at))


def historical_employee(employee_id, session):
    if not employee_id:
        return None
    return session.get(Employee, employee_id) or session.get(EmployeeIdentity, employee_id)


@event.listens_for(Employee, 'after_insert')
def _record_employee_identity(_mapper, connection, employee):
    if not inspect(connection).has_table('employee_identities'):
        # Historical migration fixtures/owner maintenance may insert accounts at
        # an older revision. The explicit identity migration backfills them.
        # A live request must never create an untracked responsibility identity.
        if has_request_context():
            from .api.errors import ApiError
            raise ApiError('数据库升级未完成，暂不能新建账号', 503, 'SCHEMA_UPGRADE_REQUIRED')
        return
    ensure_employee_identity(connection, employee)
