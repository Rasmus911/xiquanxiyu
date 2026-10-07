"""grant mobile full access to the three existing owner accounts

Revision ID: 20260920_mobile_access
Revises: 20260919_session_version
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_mobile_access"
down_revision = "20260919_session_version"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("employees", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "mobile_full_access",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.execute(
        sa.text(
            "UPDATE employees SET mobile_full_access = TRUE "
            "WHERE role = 'admin' AND ("
            "username IN (:owner_one, :owner_two, :owner_three) OR "
            "display_name IN (:owner_one, :owner_two, :owner_three))"
        ).bindparams(
            owner_one="于在跃",
            owner_two="李丽娜",
            owner_three="于景辉",
        )
    )


def downgrade():
    with op.batch_alter_table("employees", schema=None) as batch_op:
        batch_op.drop_column("mobile_full_access")
