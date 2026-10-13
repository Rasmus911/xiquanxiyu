"""Ephemeral print data, deliberately separate from financial order evidence."""
from .extensions import db
from .models import PeriodMixin, TimestampMixin


class ServicePrintJob(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = 'service_print_jobs'
    visit_id = db.Column(db.String(36), db.ForeignKey('visits.id'), nullable=False, index=True)
    terminal_id = db.Column(db.String(36), db.ForeignKey('terminals.id'), nullable=False)
    employee_id = db.Column(db.String(36), db.ForeignKey('employee_identities.id'), nullable=False)
    submission_key = db.Column(db.String(100), nullable=False, unique=True)
    bath_area = db.Column(db.String(10), nullable=False, index=True)
    snapshot = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(500))
    printed_at = db.Column(db.DateTime(timezone=True))


class ServicePrintAttempt(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = 'service_print_attempts'
    job_id = db.Column(db.String(36), db.ForeignKey('service_print_jobs.id'), nullable=False, index=True)
    request_key = db.Column(db.String(100), nullable=False, unique=True)
    employee_id = db.Column(db.String(36), db.ForeignKey('employee_identities.id'), nullable=False)
    terminal_id = db.Column(db.String(36), db.ForeignKey('terminals.id'), nullable=False)
    mode = db.Column(db.String(12), nullable=False)
    success = db.Column(db.Boolean)
    error = db.Column(db.String(500))
    finished_at = db.Column(db.DateTime(timezone=True))


class SettlementPrintAttempt(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = 'settlement_print_attempts'
    job_id = db.Column(db.String(36), db.ForeignKey('print_jobs.id'), nullable=False, index=True)
    request_key = db.Column(db.String(100), nullable=False, unique=True)
    employee_id = db.Column(db.String(36), db.ForeignKey('employee_identities.id'), nullable=False)
    terminal_id = db.Column(db.String(36), db.ForeignKey('terminals.id'), nullable=False)
    mode = db.Column(db.String(12), nullable=False)
    success = db.Column(db.Boolean)
    error = db.Column(db.String(500))
    finished_at = db.Column(db.DateTime(timezone=True))
