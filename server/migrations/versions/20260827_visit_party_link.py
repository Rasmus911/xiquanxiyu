"""add visit party linkage

Revision ID: 20260827_party_link
Revises: 65fcdab61618
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op


revision = "20260827_party_link"
down_revision = "65fcdab61618"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("visits", schema=None) as batch_op:
        batch_op.add_column(sa.Column("party_id", sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f("ix_visits_party_id"), ["party_id"], unique=False)


def downgrade():
    with op.batch_alter_table("visits", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_visits_party_id"))
        batch_op.drop_column("party_id")
