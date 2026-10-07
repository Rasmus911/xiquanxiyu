"""Independent base-unit stock, immutable movements and consumption snapshots."""
from alembic import op

revision = '20261005_independent_stock'
down_revision = '20261004_catalog_packages'
branch_labels = None
depends_on = None


def upgrade():
    from app.schema_maintenance import upgrade_independent_stock_schema
    upgrade_independent_stock_schema(op.get_bind())


def downgrade():
    raise RuntimeError('Restore a verified backup; stock and consumption evidence must not be removed')
