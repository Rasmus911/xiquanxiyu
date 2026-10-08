from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Index, event

from .extensions import db


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


MONEY = db.Numeric(12, 2)
QUANTITY = db.Numeric(12, 3)


class TimestampMixin:
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    version = db.Column(db.Integer, nullable=False, default=1)


class BusinessPeriod(TimestampMixin, db.Model):
    __tablename__ = "business_periods"
    closed_at = db.Column(db.DateTime(timezone=True))


class BusinessStateModel(db.Model):
    __tablename__ = "business_state"
    __table_args__ = (db.CheckConstraint("id = 1", name="single_business_state"),)
    id = db.Column(db.Integer, primary_key=True, default=1)
    period_id = db.Column(db.String(36), db.ForeignKey("business_periods.id"), nullable=False)
    business_revision = db.Column(db.Integer, nullable=False, default=0)
    policy_version = db.Column(db.Integer, nullable=False, default=0)
    maintenance = db.Column(db.Boolean, nullable=False, default=False)
    maintenance_reset_id = db.Column(db.String(36))


class AccessPolicyModel(TimestampMixin, db.Model):
    __tablename__ = "access_policies"
    owner_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    mobile_employee_ids = db.Column(db.JSON, nullable=False)
    administrator_employee_ids = db.Column(db.JSON, nullable=False, default=list, server_default='[]')
    policy_version = db.Column(db.Integer, nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)


class ResetTaskModel(TimestampMixin, db.Model):
    __tablename__ = "reset_tasks"
    idempotency_key = db.Column(db.String(100), nullable=False, unique=True)
    owner_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    old_period_id = db.Column(db.String(36), db.ForeignKey("business_periods.id"), nullable=False)
    new_period_id = db.Column(db.String(36), db.ForeignKey("business_periods.id"))
    status = db.Column(db.String(30), nullable=False, default="queued")
    stage = db.Column(db.String(80), nullable=False, default="queued")
    error_code = db.Column(db.String(80))
    message = db.Column(db.String(500))
    # Private backup metadata; API serializers must whitelist public fields.
    backup = db.Column(db.JSON)
    context = db.Column(db.JSON, nullable=False, default=dict)


class ResetEventModel(TimestampMixin, db.Model):
    __tablename__ = "reset_events"
    reset_id = db.Column(db.String(36), db.ForeignKey("reset_tasks.id"), nullable=False, unique=True)
    data = db.Column(db.JSON, nullable=False)
    delivered_at = db.Column(db.DateTime(timezone=True))


class PeriodMixin:
    period_id = db.Column(db.String(36), db.ForeignKey("business_periods.id"), nullable=False, index=True)


class Employee(TimestampMixin, db.Model):
    __tablename__ = "employees"

    username = db.Column(db.String(50), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="cashier", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    mobile_full_access = db.Column(db.Boolean, nullable=False, default=False)
    allowed_channels = db.Column(db.JSON, nullable=False, default=list, server_default='[]')
    deleted_at = db.Column(db.DateTime(timezone=True))
    session_version = db.Column(db.Integer, nullable=False, default=1)
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))


class Terminal(TimestampMixin, db.Model):
    __tablename__ = "terminals"

    code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    printer_name = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_seen_at = db.Column(db.DateTime(timezone=True))


class SystemSetting(TimestampMixin, db.Model):
    __tablename__ = "system_settings"

    key = db.Column(db.String(100), nullable=False, unique=True, index=True)
    value = db.Column(db.JSON, nullable=False)
    description = db.Column(db.String(255))


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    chain_index = db.Column(db.Integer, nullable=False, unique=True, index=True)
    employee_id = db.Column(db.String(36), db.ForeignKey("employees.id"), index=True)
    terminal_id = db.Column(db.String(36), db.ForeignKey("terminals.id"), index=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=False, index=True)
    entity_id = db.Column(db.String(80), index=True)
    details = db.Column(db.JSON, nullable=False, default=dict)
    request_id = db.Column(db.String(80), index=True)
    prev_hash = db.Column(db.String(64), nullable=False)
    current_hash = db.Column(db.String(64), nullable=False, unique=True)
    integrity_version = db.Column(db.Integer, nullable=False, default=2)
    context = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def _protect_audit_log(_mapper, _connection, _target):
    raise ValueError("审计日志只允许新增，禁止修改或删除")


class RevokedSession(db.Model):
    __tablename__ = "revoked_sessions"

    id = db.Column(db.String(36), primary_key=True)
    employee_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Wristband(TimestampMixin, db.Model):
    __tablename__ = "wristbands"

    number = db.Column(db.String(30), nullable=False, unique=True, index=True)
    bath_area = db.Column(db.String(20), nullable=False, default='other', server_default='other')
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    status = db.Column(db.String(20), nullable=False, default="available", index=True)
    note = db.Column(db.String(255))


class Member(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "members"

    __table_args__ = (db.UniqueConstraint("period_id", "phone", name="uq_members_period_phone"),)
    phone = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(80))
    deleted_at = db.Column(db.DateTime(timezone=True))
    balance = db.Column(MONEY, nullable=False, default=Decimal("0.00"))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    note = db.Column(db.String(255))


class Visit(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "visits"

    wristband_id = db.Column(db.String(36), db.ForeignKey("wristbands.id"), nullable=False, index=True)
    member_id = db.Column(db.String(36), db.ForeignKey("members.id"), index=True)
    party_id = db.Column(db.String(36), index=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    opened_by_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    opened_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    closed_at = db.Column(db.DateTime(timezone=True))
    note = db.Column(db.String(255))


Index(
    "uq_visits_active_wristband",
    Visit.period_id,
    Visit.wristband_id,
    unique=True,
    postgresql_where=Visit.status.in_(["open", "settling"]),
    sqlite_where=Visit.status.in_(["open", "settling"]),
)


class CatalogItem(TimestampMixin, db.Model):
    __tablename__ = "catalog_items"

    kind = db.Column(db.String(30), nullable=False, index=True)
    category = db.Column(db.String(80), nullable=False, default="默认")
    name = db.Column(db.String(120), nullable=False)
    deleted_at = db.Column(db.DateTime(timezone=True))
    reference_code = db.Column(db.String(80), nullable=True)
    package_definition = db.Column(db.JSON, nullable=True)
    __table_args__ = (db.Index('uq_catalog_reference_code', 'reference_code', unique=True),)
    # frontdesk: only desktop cashier; scrub/rest: matching mobile role; both: all mobile roles.
    mobile_scope = db.Column(db.String(20), nullable=False, default="frontdesk")
    price = db.Column(MONEY, nullable=False, default=Decimal("0.00"))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    stock_tracked = db.Column(db.Boolean, nullable=False, default=False)
    stock_quantity = db.Column(QUANTITY, nullable=False, default=Decimal("0"))
    low_stock_threshold = db.Column(QUANTITY, nullable=False, default=Decimal("0"))
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class OrderItem(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "order_items"

    visit_id = db.Column(db.String(36), db.ForeignKey("visits.id"), nullable=False, index=True)
    catalog_item_id = db.Column(db.String(36), db.ForeignKey("catalog_items.id"), index=True)
    kind = db.Column(db.String(30), nullable=False)
    name_snapshot = db.Column(db.String(120), nullable=False)
    unit_price = db.Column(MONEY, nullable=False)
    quantity = db.Column(QUANTITY, nullable=False, default=Decimal("1"))
    inventory_mode = db.Column(db.String(20), nullable=False, default='legacy', server_default='legacy')
    covered_quantity = db.Column(QUANTITY, nullable=False, default=Decimal('0'), server_default='0')
    package_order_item_id = db.Column(db.String(36), db.ForeignKey('order_items.id'), nullable=True)
    package_snapshot = db.Column(db.JSON, nullable=True)
    __table_args__ = (db.CheckConstraint('covered_quantity >= 0 AND covered_quantity <= quantity', name='covered_quantity_bounds'),)
    total_amount = db.Column(MONEY, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    service_employee_id = db.Column(db.String(36), db.ForeignKey("employees.id"))
    created_by_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    voided_by_id = db.Column(db.String(36), db.ForeignKey("employees.id"))
    void_reason = db.Column(db.String(255))
    voided_at = db.Column(db.DateTime(timezone=True))


class Shift(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "shifts"

    employee_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False, index=True)
    terminal_id = db.Column(db.String(36), db.ForeignKey("terminals.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    opening_cash = db.Column(MONEY, nullable=False, default=Decimal("0.00"))
    expected_cash = db.Column(MONEY)
    actual_cash = db.Column(MONEY)
    difference = db.Column(MONEY)
    opened_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    closed_at = db.Column(db.DateTime(timezone=True))
    close_note = db.Column(db.String(255))


class Settlement(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "settlements"

    number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="completed", index=True)
    total_amount = db.Column(MONEY, nullable=False)
    paid_amount = db.Column(MONEY, nullable=False)
    created_by_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    terminal_id = db.Column(db.String(36), db.ForeignKey("terminals.id"), nullable=False)
    shift_id = db.Column(db.String(36), db.ForeignKey("shifts.id"), index=True)
    member_id = db.Column(db.String(36), db.ForeignKey("members.id"), index=True)
    idempotency_key = db.Column(db.String(100), nullable=False, unique=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class SettlementVisit(PeriodMixin, db.Model):
    __tablename__ = "settlement_visits"

    settlement_id = db.Column(db.String(36), db.ForeignKey("settlements.id"), primary_key=True)
    visit_id = db.Column(db.String(36), db.ForeignKey("visits.id"), primary_key=True)
    amount = db.Column(MONEY, nullable=False)


class Payment(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "payments"

    settlement_id = db.Column(db.String(36), db.ForeignKey("settlements.id"), nullable=False, index=True)
    shift_id = db.Column(db.String(36), db.ForeignKey("shifts.id"), index=True)
    method = db.Column(db.String(30), nullable=False, index=True)
    amount = db.Column(MONEY, nullable=False)
    reference = db.Column(db.String(120))
    kind = db.Column(db.String(20), nullable=False, default="payment")
    original_payment_id = db.Column(db.String(36), db.ForeignKey("payments.id"))


class StoredValueLedger(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "stored_value_ledgers"

    member_id = db.Column(db.String(36), db.ForeignKey("members.id"), nullable=False, index=True)
    amount = db.Column(MONEY, nullable=False)
    balance_after = db.Column(MONEY, nullable=False)
    entry_type = db.Column(db.String(30), nullable=False, index=True)
    payment_method = db.Column(db.String(30))
    shift_id = db.Column(db.String(36), db.ForeignKey("shifts.id"), index=True)
    settlement_id = db.Column(db.String(36), db.ForeignKey("settlements.id"))
    operator_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    note = db.Column(db.String(255))
    idempotency_key = db.Column(db.String(100), unique=True)


class MemberPass(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "member_passes"

    member_id = db.Column(db.String(36), db.ForeignKey("members.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    remaining_count = db.Column(db.Integer, nullable=False, default=0)
    valid_until = db.Column(db.Date)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class PassLedger(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "pass_ledgers"

    member_pass_id = db.Column(db.String(36), db.ForeignKey("member_passes.id"), nullable=False, index=True)
    delta = db.Column(db.Integer, nullable=False)
    balance_after = db.Column(db.Integer, nullable=False)
    entry_type = db.Column(db.String(30), nullable=False)
    amount_paid = db.Column(MONEY, nullable=False, default=Decimal("0.00"))
    payment_method = db.Column(db.String(30))
    idempotency_key = db.Column(db.String(100), unique=True)
    settlement_id = db.Column(db.String(36), db.ForeignKey("settlements.id"))
    operator_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    note = db.Column(db.String(255))


class InventoryMovement(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "inventory_movements"

    catalog_item_id = db.Column(db.String(36), db.ForeignKey("catalog_items.id"), nullable=False, index=True)
    movement_type = db.Column(db.String(30), nullable=False, index=True)
    quantity = db.Column(QUANTITY, nullable=False)
    balance_after = db.Column(QUANTITY, nullable=False)
    reference_type = db.Column(db.String(40))
    reference_id = db.Column(db.String(36), index=True)
    operator_id = db.Column(db.String(36), db.ForeignKey("employees.id"), nullable=False)
    note = db.Column(db.String(255))
    idempotency_key = db.Column(db.String(100), unique=True)


class StockItem(TimestampMixin, db.Model):
    __tablename__ = 'stock_items'
    __table_args__ = (db.CheckConstraint('stock_quantity >= 0', name='stock_balance_nonnegative'),
                      db.CheckConstraint('units_per_package > 0', name='stock_factor_positive'))
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False, default='默认')
    base_unit = db.Column(db.String(20), nullable=False)
    package_unit = db.Column(db.String(20), nullable=False, default='')
    units_per_package = db.Column(QUANTITY, nullable=False, default=Decimal('1'))
    package_spec = db.Column(db.String(120), nullable=False, default='')
    stock_quantity = db.Column(QUANTITY, nullable=False, default=Decimal('0'))
    low_stock_threshold = db.Column(QUANTITY, nullable=False, default=Decimal('0'))
    # Optional current base-unit reference cost; never rewrites receipt costs.
    unit_cost = db.Column(MONEY, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    legacy_catalog_item_id = db.Column(db.String(36), db.ForeignKey('catalog_items.id'), unique=True)


class StockMovement(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = 'stock_movements'
    stock_item_id = db.Column(db.String(36), db.ForeignKey('stock_items.id'), nullable=False, index=True)
    movement_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(QUANTITY, nullable=False)
    balance_before = db.Column(QUANTITY, nullable=False)
    balance_after = db.Column(QUANTITY, nullable=False)
    input_quantity = db.Column(QUANTITY, nullable=False)
    input_unit = db.Column(db.String(20), nullable=False)
    conversion_factor = db.Column(QUANTITY, nullable=False)
    base_unit_snapshot = db.Column(db.String(20), nullable=False)
    package_unit_snapshot = db.Column(db.String(20), nullable=False)
    reference_type = db.Column(db.String(40))
    reference_id = db.Column(db.String(36), index=True)
    operator_id = db.Column(db.String(36), db.ForeignKey('employees.id'), nullable=False)
    reason = db.Column(db.String(255), nullable=False)


class StockCost(TimestampMixin, db.Model):
    """Append-only cost corrections; stock survives business period resets."""
    __tablename__ = 'stock_costs'
    __table_args__ = (db.UniqueConstraint('stock_movement_id', 'version', name='uq_stock_cost_revision'),
                      db.CheckConstraint('unit_cost >= 0 AND total_cost >= 0', name='stock_cost_nonnegative'))
    stock_movement_id = db.Column(db.String(36), db.ForeignKey('stock_movements.id'), nullable=False, index=True)
    unit_cost = db.Column(MONEY, nullable=False)
    total_cost = db.Column(MONEY, nullable=False)
    operator_id = db.Column(db.String(36), db.ForeignKey('employees.id'), nullable=False)


class OrderStockConsumption(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = 'order_stock_consumptions'
    __table_args__ = (db.UniqueConstraint('order_item_id', 'stock_item_id', name='uq_order_stock_consumption'),
                      db.CheckConstraint('quantity > 0', name='stock_consumption_positive'))
    order_item_id = db.Column(db.String(36), db.ForeignKey('order_items.id'), nullable=False, index=True)
    stock_item_id = db.Column(db.String(36), db.ForeignKey('stock_items.id'), nullable=False, index=True)
    stock_name_snapshot = db.Column(db.String(120), nullable=False)
    base_unit_snapshot = db.Column(db.String(20), nullable=False)
    quantity = db.Column(QUANTITY, nullable=False)


class PrintJob(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = "print_jobs"

    settlement_id = db.Column(db.String(36), db.ForeignKey("settlements.id"), nullable=False, index=True)
    terminal_id = db.Column(db.String(36), db.ForeignKey("terminals.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(500))
    printed_at = db.Column(db.DateTime(timezone=True))


class IdempotencyRecord(PeriodMixin, db.Model):
    __tablename__ = "idempotency_records"

    key = db.Column(db.String(100), primary_key=True)
    endpoint = db.Column(db.String(120), nullable=False)
    response_status = db.Column(db.Integer, nullable=False)
    response_body = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


from .registration_models import (  # noqa: E402,F401: register additive metadata
    RegistrationRateLimit, RegistrationReceipt, RegistrationTokenState, RegistrationTokenView,
)


@event.listens_for(db.metadata, "after_create")
def _install_database_guards(_metadata, connection, **_kwargs):
    from .database_guards import install_database_guards, install_period_guards

    install_database_guards(connection)
    install_period_guards(connection)
    from .business_barrier import install_barrier_guards
    install_barrier_guards(connection)
