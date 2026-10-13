"""Add physical wristband mapping and isolated sliding admission sessions."""
from alembic import op
from sqlalchemy import text

revision = '20261013_wristband_chip'
down_revision = '20261012_physical_membership'
branch_labels = None
depends_on = None


def upgrade():
    from app.models import WristbandChipBinding, WristbandScanSession
    from app.database_guards import install_database_guards, install_period_guards
    from app.business_barrier import install_barrier_guards
    connection = op.get_bind()
    for model in (WristbandChipBinding, WristbandScanSession):
        model.__table__.create(connection, checkfirst=True)
    install_database_guards(connection)
    install_period_guards(connection)
    install_barrier_guards(connection)
    if connection.dialect.name == 'postgresql':
        for role, privileges in [('xiquan_app', 'SELECT,INSERT,UPDATE'),
                                  ('xiquan_reset', 'SELECT'), ('xiquan_backup', 'SELECT')]:
            if connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role': role}).scalar():
                connection.exec_driver_sql(f'GRANT {privileges} ON wristband_chip_bindings,wristband_scan_sessions TO {role}')
        if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname='xiquan_app'")).scalar():
            connection.exec_driver_sql('REVOKE DELETE,TRUNCATE ON wristband_chip_bindings,wristband_scan_sessions FROM xiquan_app')


def downgrade():
    raise RuntimeError('Physical bindings and scan evidence require an explicitly verified recovery checkpoint')
