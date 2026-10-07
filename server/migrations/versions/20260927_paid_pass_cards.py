"""record paid pass card sales

Revision ID: 20260927_paid_pass_cards
Revises: 20260920_mobile_access
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op


revision = "20260927_paid_pass_cards"
down_revision = "20260920_mobile_access"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pass_ledgers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("amount_paid", sa.Numeric(12, 2), nullable=False, server_default="0.00")
        )
        batch_op.add_column(sa.Column("payment_method", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=100), nullable=True))
    op.create_index(
        "uq_pass_ledgers_idempotency_key",
        "pass_ledgers",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_pass_ledgers_idempotency_key", table_name="pass_ledgers")
    with op.batch_alter_table("pass_ledgers", schema=None) as batch_op:
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("payment_method")
        batch_op.drop_column("amount_paid")
