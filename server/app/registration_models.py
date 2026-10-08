"""Global registration security state; independent of business periods."""
from .extensions import db
from .models import utcnow


class RegistrationTokenState(db.Model):
    __tablename__ = 'registration_token_state'
    __table_args__ = (db.CheckConstraint('id = 1', name='single_registration_token_state'),)
    id = db.Column(db.Integer, primary_key=True)
    generation = db.Column(db.Integer, nullable=False)
    seed = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    wrong_attempts = db.Column(db.Integer, nullable=False, default=0)
    consumed_generation = db.Column(db.Integer)
    consumed_at = db.Column(db.DateTime(timezone=True))


class RegistrationRateLimit(db.Model):
    __tablename__ = 'registration_rate_limits'
    key = db.Column(db.String(64), primary_key=True)
    # Sliding window, at most ten UTC timestamps. No plaintext source address.
    attempts = db.Column(db.JSON, nullable=False, default=list)


class RegistrationReceipt(db.Model):
    __tablename__ = 'registration_receipts'
    key = db.Column(db.String(64), primary_key=True)
    terminal_id = db.Column(db.String(36), db.ForeignKey('terminals.id'), nullable=False)
    request_digest = db.Column(db.String(64), nullable=False)
    employee_id = db.Column(db.String(36), db.ForeignKey('employees.id'), nullable=False)
    generation = db.Column(db.Integer, nullable=False)
    identity = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class RegistrationTokenView(db.Model):
    __tablename__ = 'registration_token_views'
    key = db.Column(db.String(64), primary_key=True)
    employee_id = db.Column(db.String(36), db.ForeignKey('employees.id'), nullable=False)
    generation = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
