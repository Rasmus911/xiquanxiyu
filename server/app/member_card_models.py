"""Physical cards address existing member accounts; redemption rows retain evidence."""
from sqlalchemy import Index

from .extensions import db
from .models import MONEY, PeriodMixin, TimestampMixin


class MemberCardBinding(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = 'member_card_bindings'
    __table_args__ = (db.UniqueConstraint('period_id', 'card_uid', name='uq_member_cards_period_uid'),)
    member_id = db.Column(db.String(36), db.ForeignKey('members.id'), nullable=False, index=True)
    card_uid = db.Column(db.String(64), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.String(36), db.ForeignKey('employee_identities.id'), nullable=False)
    terminal_id = db.Column(db.String(36), db.ForeignKey('terminals.id'), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))
    replaced_by_id = db.Column(db.String(36), db.ForeignKey('member_card_bindings.id'))


Index('uq_member_cards_active_member', MemberCardBinding.period_id, MemberCardBinding.member_id,
    unique=True, postgresql_where=MemberCardBinding.is_active.is_(True),
    sqlite_where=MemberCardBinding.is_active.is_(True))


class SettlementPassRedemption(PeriodMixin, TimestampMixin, db.Model):
    __tablename__ = 'settlement_pass_redemptions'
    settlement_id = db.Column(db.String(36), db.ForeignKey('settlements.id'), nullable=False, index=True)
    visit_id = db.Column(db.String(36), db.ForeignKey('visits.id'), nullable=False, index=True)
    order_item_id = db.Column(db.String(36), db.ForeignKey('order_items.id'), nullable=False, index=True)
    member_pass_id = db.Column(db.String(36), db.ForeignKey('member_passes.id'), nullable=False, index=True)
    count = db.Column(db.Integer, nullable=False)
    amount = db.Column(MONEY, nullable=False)
