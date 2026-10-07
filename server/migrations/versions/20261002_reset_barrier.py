"""Install durable maintenance ownership and guards; never perform a reset."""
import sqlalchemy as sa
from alembic import op

revision = '20261002_reset_barrier'
down_revision = '20261002_business_period_reset'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column['name'] for column in sa.inspect(connection).get_columns('business_state')}
    if 'maintenance_reset_id' not in columns:
        op.add_column('business_state', sa.Column('maintenance_reset_id', sa.String(36), nullable=True))
    from app.business_barrier import install_barrier_guards
    install_barrier_guards(connection)


def downgrade():
    raise RuntimeError('Restore a verified backup; maintenance ownership cannot be dropped safely')
