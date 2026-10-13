"""Physical identifiers for existing members and append-only pass redemption evidence."""
from alembic import op
from sqlalchemy import String, inspect, text

revision = '20261012_physical_membership'
down_revision = '20261011_service_receipts'
branch_labels = None
depends_on = None


def upgrade():
    from app.models import MemberCardBinding, SettlementPassRedemption
    from app.database_guards import install_database_guards, install_period_guards
    from app.business_barrier import install_barrier_guards
    connection = op.get_bind()
    columns = {column['name']: column for column in inspect(connection).get_columns('members')}
    legacy = connection.exec_driver_sql('PRAGMA legacy_alter_table').scalar_one() if connection.dialect.name == 'sqlite' else None
    try:
        if legacy is not None:
            connection.exec_driver_sql('PRAGMA legacy_alter_table=ON')
        if not columns['phone']['nullable']:
            if connection.dialect.name == 'sqlite':
                with op.batch_alter_table('members') as batch:
                    batch.alter_column('phone', existing_type=String(20), nullable=True)
            else:
                op.alter_column('members', 'phone', existing_type=String(20), nullable=True)
        if 'holder_surname' not in columns:
            from sqlalchemy import Column
            op.add_column('members', Column('holder_surname', String(40), nullable=True))
    finally:
        if legacy is not None:
            connection.exec_driver_sql(f'PRAGMA legacy_alter_table={int(legacy)}')
    for model in (MemberCardBinding, SettlementPassRedemption):
        model.__table__.create(connection, checkfirst=True)
    install_database_guards(connection)
    install_period_guards(connection)
    install_barrier_guards(connection)
    if connection.dialect.name == 'postgresql':
        for role, privileges in [('xiquan_app', 'SELECT,INSERT'), ('xiquan_reset', 'SELECT'), ('xiquan_backup', 'SELECT')]:
            if connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role': role}).scalar():
                connection.exec_driver_sql(f'GRANT {privileges} ON member_card_bindings,settlement_pass_redemptions TO {role}')
        if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname='xiquan_app'")).scalar():
            for table in ('member_card_bindings', 'settlement_pass_redemptions'):
                connection.exec_driver_sql(f'REVOKE UPDATE,DELETE,TRUNCATE ON {table} FROM xiquan_app')
                names = ','.join('"'+column['name']+'"' for column in inspect(connection).get_columns(table))
                connection.exec_driver_sql(f'REVOKE UPDATE({names}) ON {table} FROM xiquan_app')
            connection.exec_driver_sql('GRANT UPDATE(is_active,revoked_at,replaced_by_id,version,updated_at) ON member_card_bindings TO xiquan_app')


def downgrade():
    raise RuntimeError('Physical card identities and redemption evidence cannot be discarded; restore a verified checkpoint')
