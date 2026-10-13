"""Add manual stocktake input costs and immutable pending Excel evidence."""
from alembic import op
import sqlalchemy as sa

revision = '20261013_manual_inventory_excel'
down_revision = '20261013_wristband_chip'
branch_labels = None
depends_on = None


def upgrade():
    from app.models import StockImportPending, StockImportResolution
    from app.database_guards import install_database_guards, install_period_guards
    from app.business_barrier import install_barrier_guards
    connection = op.get_bind()
    columns = {row['name'] for row in sa.inspect(connection).get_columns('stock_items')}
    if 'reference_cost' not in columns:
        op.add_column('stock_items', sa.Column('reference_cost', sa.Numeric(12, 2), nullable=True))
    if 'cost_basis' not in columns:
        op.add_column('stock_items', sa.Column('cost_basis', sa.String(7), nullable=True))
    for model in (StockImportPending, StockImportResolution):
        model.__table__.create(connection, checkfirst=True)
    install_database_guards(connection)
    install_period_guards(connection)
    install_barrier_guards(connection)
    if connection.dialect.name == 'postgresql':
        for role, privileges in [('xiquan_app', 'SELECT,INSERT'), ('xiquan_reset', 'SELECT'), ('xiquan_backup', 'SELECT')]:
            if connection.execute(sa.text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role': role}).scalar():
                connection.exec_driver_sql(f'GRANT {privileges} ON stock_import_pending,stock_import_resolutions TO {role}')
        if connection.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname='xiquan_app'")).scalar():
            connection.exec_driver_sql('REVOKE UPDATE,DELETE,TRUNCATE ON stock_import_pending,stock_import_resolutions FROM xiquan_app')


def downgrade():
    raise RuntimeError('Stocktake evidence must be preserved; use an explicitly verified recovery checkpoint')
