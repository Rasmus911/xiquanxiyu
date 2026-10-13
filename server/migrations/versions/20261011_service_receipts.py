"""Independent ephemeral service tickets and idempotent printing attempts."""
from alembic import op
from sqlalchemy import text

revision = '20261011_service_receipts'
down_revision = '20261011_employee_identity'
branch_labels = None
depends_on = None


def upgrade():
    from app.receipt_models import ServicePrintJob, ServicePrintAttempt, SettlementPrintAttempt
    from app.database_guards import install_period_guards
    from app.business_barrier import install_barrier_guards
    connection = op.get_bind()
    for model in (ServicePrintJob,ServicePrintAttempt,SettlementPrintAttempt):
        model.__table__.create(connection,checkfirst=True)
    install_period_guards(connection)
    install_barrier_guards(connection)
    if connection.dialect.name=='postgresql':
        for role,privileges in [('xiquan_app','SELECT, INSERT'),('xiquan_reset','SELECT'),('xiquan_backup','SELECT')]:
            if connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'),{'role':role}).scalar():
                connection.exec_driver_sql(f'GRANT {privileges} ON service_print_jobs,service_print_attempts,settlement_print_attempts TO {role}')
        if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname='xiquan_app'")).scalar():
            for table in ('print_jobs','service_print_jobs','service_print_attempts','settlement_print_attempts'):
                connection.exec_driver_sql(f'REVOKE UPDATE,DELETE,TRUNCATE ON {table} FROM xiquan_app')
                columns = 'status,attempts,last_error,printed_at,updated_at' if table.endswith('jobs') else 'success,error,finished_at,updated_at'
                # Also remove historical column-level grants before narrowing.
                from sqlalchemy import inspect
                names = ','.join('"'+c['name']+'"' for c in inspect(connection).get_columns(table))
                connection.exec_driver_sql(f'REVOKE UPDATE({names}) ON {table} FROM xiquan_app')
                connection.exec_driver_sql(f'GRANT SELECT,INSERT ON {table} TO xiquan_app')
                connection.exec_driver_sql(f'GRANT UPDATE({columns}) ON {table} TO xiquan_app')


def downgrade():
    raise RuntimeError('Explicitly archive ephemeral print evidence before any owner-directed downgrade')
