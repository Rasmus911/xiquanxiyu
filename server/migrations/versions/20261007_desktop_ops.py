"""Add recoverable member and catalog tombstones without changing financial rows."""
from alembic import op

revision = '20261007_desktop_ops'
down_revision = '20261005_independent_stock'
branch_labels = None
depends_on = None


def upgrade():
    from app.schema_maintenance import upgrade_desktop_ops_schema
    upgrade_desktop_ops_schema(op.get_bind())


def downgrade():
    raise RuntimeError('Restore a verified backup; archive evidence must not be removed')
