"""Append receiving cost evidence and initialize the fifteen-percent alert."""
from alembic import op

revision = '20261007_insights_cost'
down_revision = '20261007_desktop_ops'
branch_labels = None
depends_on = None


def upgrade():
    from app.schema_maintenance import upgrade_insights047_schema
    upgrade_insights047_schema(op.get_bind())


def downgrade():
    raise RuntimeError('Retain cost evidence; use a verified, explicit recovery procedure')
