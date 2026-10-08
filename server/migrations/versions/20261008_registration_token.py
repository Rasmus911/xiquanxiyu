"""Persistent shared registration authorization; no existing data changes."""
from alembic import op

revision = '20261008_registration_token'
down_revision = '20261007_ordering_cost'
branch_labels = None
depends_on = None


def upgrade():
    from app.business_barrier import install_barrier_guards
    from app.database_guards import install_database_guards
    from app.registration_models import (
        RegistrationRateLimit, RegistrationReceipt, RegistrationTokenState, RegistrationTokenView,
    )
    connection = op.get_bind()
    for model in (RegistrationTokenState, RegistrationRateLimit, RegistrationReceipt, RegistrationTokenView):
        model.__table__.create(connection, checkfirst=True)
    install_database_guards(connection)
    install_barrier_guards(connection)
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('''DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_app') THEN
            GRANT SELECT,INSERT,UPDATE ON registration_token_state,registration_rate_limits TO xiquan_app;
            GRANT SELECT,INSERT ON registration_receipts,registration_token_views TO xiquan_app;
            REVOKE DELETE,TRUNCATE ON registration_token_state,registration_rate_limits FROM xiquan_app;
            REVOKE UPDATE,DELETE,TRUNCATE ON registration_receipts,registration_token_views FROM xiquan_app;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_reset') THEN
            GRANT SELECT ON registration_token_state,registration_rate_limits,registration_receipts,
                            registration_token_views TO xiquan_reset;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_backup') THEN
            GRANT SELECT ON registration_token_state,registration_rate_limits,registration_receipts,
                            registration_token_views TO xiquan_backup;
          END IF;
        END $$''')


def downgrade():
    raise RuntimeError('Retain registration security evidence; use a verified explicit recovery procedure')
