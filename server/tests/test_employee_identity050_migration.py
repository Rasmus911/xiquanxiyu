"""Exercise real Alembic upgrade with historical actor IDs and guarded evidence."""
from pathlib import Path

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.config import TestConfig
from app.extensions import db


def test_identity_upgrade_preserves_old_values_and_retargets_only_history(tmp_path):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'identity.sqlite').as_posix()}"
    application = create_app(MigrationConfig)
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    with application.app_context():
        upgrade(directory=migrations, revision='20261008_registration_token')
        with db.engine.begin() as connection:
            for name in ('stock_movements', 'stock_costs', 'registration_receipts', 'registration_token_views'):
                actor = next(fk for fk in inspect(connection).get_foreign_keys(name)
                             if fk['constrained_columns'] in [['operator_id'], ['employee_id']])
                assert actor['referred_table'] == 'employees'
            connection.execute(text("""INSERT INTO employees
                (id,created_at,updated_at,version,username,display_name,password_hash,role,is_active,
                 mobile_full_access,session_version,failed_login_attempts,allowed_channels,deleted_at)
                VALUES (:id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,:name,'原姓名','opaque-original-hash',
                        :role,:active,FALSE,7,0,'[]',:deleted)"""), [
                {'id':'original-admin', 'name':'original-admin', 'role':'admin', 'active':True, 'deleted':None},
                {'id':'removed-login', 'name':'13900001234', 'role':'cashier', 'active':False,
                 'deleted':'2026-10-01 00:00:00'},
            ])
            before = dict(connection.execute(text('SELECT * FROM employees WHERE id=\'original-admin\'')).mappings().one())
        from app.audit_service import write_audit, verify_audit_chain
        write_audit('employee.update', 'employee', 'removed-login', {'historical':True}, employee_id='removed-login')
        db.session.commit()
        with db.engine.connect() as connection:
            audit_before = [dict(r) for r in connection.execute(text('SELECT * FROM audit_logs')).mappings()]
        upgrade(directory=migrations, revision='20261011_employee_identity')
        with db.engine.connect() as connection:
            assert dict(connection.execute(text('SELECT * FROM employees WHERE id=\'original-admin\'')).mappings().one()) == before
            assert connection.execute(text('SELECT count(*) FROM employees WHERE id=\'removed-login\'')).scalar_one() == 0
            assert connection.execute(text('SELECT username FROM employee_identities WHERE id=\'removed-login\'')).scalar_one() == '13900001234'
            assert [dict(r) for r in connection.execute(text('SELECT * FROM audit_logs')).mappings()] == audit_before
            from app.employee_identity import HISTORICAL_EMPLOYEE_REFERENCES
            for table, columns in HISTORICAL_EMPLOYEE_REFERENCES.items():
                for column in columns:
                    fk = next(fk for fk in inspect(connection).get_foreign_keys(table)
                              if fk['constrained_columns'] == [column])
                    assert fk['referred_table'] == 'employee_identities'
            for table in ('access_policies', 'reset_tasks'):
                owner_fk = next(fk for fk in inspect(connection).get_foreign_keys(table)
                                if fk['constrained_columns'] == ['owner_id'])
                assert owner_fk['referred_table'] == 'employees'
            assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        db.session.expire_all()
        assert verify_audit_chain() == (True, None)
        db.session.remove()
        db.engine.dispose()
