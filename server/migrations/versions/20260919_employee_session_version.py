"""add employee session version

Revision ID: 20260919_session_version
Revises: 20260830_mobile_scope
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op


revision = "20260919_session_version"
down_revision = "20260830_mobile_scope"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("employees", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("session_version", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade():
    with op.batch_alter_table("employees", schema=None) as batch_op:
        batch_op.drop_column("session_version")
