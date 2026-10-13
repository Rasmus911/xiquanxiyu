"""Separate actual employee logins from immutable historical responsibility."""
import json

from alembic import op
from sqlalchemy import inspect, text

revision = '20261011_employee_identity'
down_revision = '20261008_registration_token'
branch_labels = None
depends_on = None


def _retarget_history(connection, references):
    names = {'fk':'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'}
    for table, columns in references.items():
        foreign_keys = inspect(connection).get_foreign_keys(table)
        changes = [fk for fk in foreign_keys if fk['constrained_columns'] in [[c] for c in columns]
                   and fk['referred_table'] == 'employees']
        if not changes:
            continue
        with op.batch_alter_table(table, naming_convention=names) as batch:
            for fk in changes:
                column = fk['constrained_columns'][0]
                batch.drop_constraint(fk['name'] or f'fk_{table}_{column}_employees', type_='foreignkey')
                batch.create_foreign_key(f'fk_{table}_{column}_employee_identities', 'employee_identities',
                    [column], ['id'])


def upgrade():
    from app.employee_identity import HISTORICAL_EMPLOYEE_REFERENCES
    from app.models import EmployeeIdentity
    from app.database_guards import install_database_guards, install_period_guards
    from app.business_barrier import install_barrier_guards
    connection = op.get_bind()
    EmployeeIdentity.__table__.create(connection, checkfirst=True)
    connection.exec_driver_sql('''INSERT INTO employee_identities(id,username,display_name,role,created_at)
        SELECT e.id,e.username,e.display_name,e.role,e.created_at FROM employees e
        WHERE NOT EXISTS (SELECT 1 FROM employee_identities h WHERE h.id=e.id)''')
    # Retain cross-table triggers during SQLite's drop/copy/rename sequence.
    # Do not rewrite schema text or disable audit protection.
    legacy = connection.exec_driver_sql('PRAGMA legacy_alter_table').scalar_one() if connection.dialect.name == 'sqlite' else None
    try:
        if legacy is not None:
            connection.exec_driver_sql('PRAGMA legacy_alter_table=ON')
        _retarget_history(connection, HISTORICAL_EMPLOYEE_REFERENCES)
    finally:
        if legacy is not None:
            connection.exec_driver_sql(f'PRAGMA legacy_alter_table={int(legacy)}')
    protected = set()
    for row in connection.execute(text('SELECT owner_id,mobile_employee_ids,administrator_employee_ids FROM access_policies')).mappings():
        protected.add(row['owner_id'])
        for key in ('mobile_employee_ids', 'administrator_employee_ids'):
            values = json.loads(row[key]) if isinstance(row[key], str) else row[key]
            protected.update(values or [])
    protected.update(connection.execute(text('SELECT owner_id FROM reset_tasks')).scalars())
    removable = connection.execute(text("SELECT id FROM employees WHERE deleted_at IS NOT NULL AND role<>'admin'")).scalars()
    for employee_id in removable:
        if employee_id not in protected:
            connection.execute(text('DELETE FROM employees WHERE id=:id'), {'id':employee_id})
    install_database_guards(connection)
    install_period_guards(connection)
    install_barrier_guards(connection)
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('''DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_app') THEN
            GRANT SELECT,INSERT ON employee_identities TO xiquan_app;
            REVOKE UPDATE,DELETE,TRUNCATE ON employee_identities FROM xiquan_app;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_reset') THEN
            GRANT SELECT ON employee_identities TO xiquan_reset;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_backup') THEN
            GRANT SELECT ON employee_identities TO xiquan_backup;
          END IF;
        END $$''')


def downgrade():
    raise RuntimeError('Deleted login credentials cannot be reconstructed; use checkpoint-specific recovery')
