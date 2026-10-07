"""add mobile sales scope

Revision ID: 20260830_mobile_scope
Revises: 20260827_party_link
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op


revision = "20260830_mobile_scope"
down_revision = "20260827_party_link"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("catalog_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("mobile_scope", sa.String(length=20), nullable=False, server_default="frontdesk")
        )
    op.execute(
        "UPDATE catalog_items SET mobile_scope = 'scrub' "
        "WHERE category IN ('搓澡助浴', '组合项目', '洗浴用品')"
    )
    op.execute(
        "UPDATE catalog_items SET mobile_scope = 'rest' "
        "WHERE category IN ('理疗按摩', '饮品', '承德特色饮品', '食品')"
    )


def downgrade():
    with op.batch_alter_table("catalog_items", schema=None) as batch_op:
        batch_op.drop_column("mobile_scope")
