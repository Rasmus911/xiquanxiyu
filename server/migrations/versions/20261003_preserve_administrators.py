"""Allow explicit existing administrators without touching employees or business data."""
import sqlalchemy as sa
from alembic import op

revision = '20261003_preserve_administrators'
down_revision = '20261002_reset_barrier'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column['name'] for column in sa.inspect(connection).get_columns('access_policies')}
    if 'administrator_employee_ids' not in columns:
        op.add_column('access_policies', sa.Column('administrator_employee_ids', sa.JSON(),
                                                  nullable=False, server_default='[]'))


def downgrade():
    raise RuntimeError('Restore a verified backup; do not silently remove administrator bindings')
