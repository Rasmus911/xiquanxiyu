"""Add operational structure, retaining every original business value and row."""
from alembic import op

revision = '20261004_catalog_packages'
down_revision = '20261004_employee_entries'
branch_labels = None
depends_on = None


def upgrade():
    from app.schema_maintenance import upgrade_operations_schema
    upgrade_operations_schema(op.get_bind())


def downgrade():
    raise RuntimeError('Restore a verified backup; package and area evidence must not be removed')
