"""Explicit ordinary employee entry grants; preserve existing identities and passwords."""
import sqlalchemy as sa
from alembic import op

revision = '20261004_employee_entries'
down_revision = '20261003_preserve_administrators'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('employees')}
    if 'allowed_channels' not in columns:
        op.add_column('employees', sa.Column('allowed_channels', sa.JSON(), nullable=False, server_default='[]'))
    if 'deleted_at' not in columns:
        op.add_column('employees', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    raise RuntimeError('Restore a verified backup; do not remove employee entry or deletion evidence')
