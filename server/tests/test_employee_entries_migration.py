"""Adding entry grants preserves every old employee identity and credential."""
from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.config import TestConfig
from app.extensions import db


@pytest.mark.parametrize('runtime', [False, True])
def test_entry_migration_preserves_old_employee_data(tmp_path, runtime):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'entries.sqlite').as_posix()}"

    application = create_app(MigrationConfig)
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    with application.app_context():
        upgrade(directory=migrations, revision='20261003_preserve_administrators')
        with db.engine.begin() as connection:
            columns = {c['name'] for c in inspect(connection).get_columns('employees')}
            for name in ('allowed_channels', 'deleted_at'):
                if name in columns:
                    connection.exec_driver_sql(f'ALTER TABLE employees DROP COLUMN {name}')
            connection.execute(text("""INSERT INTO employees
                (id,created_at,updated_at,version,username,display_name,password_hash,role,is_active,
                 mobile_full_access,session_version,failed_login_attempts)
                VALUES (:id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,:name,'原姓名','opaque-original-hash',
                        :role,:active,FALSE,7,0)"""), [
                {'id': '00000000-0000-0000-0000-000000000031', 'name': 'original-admin', 'role': 'admin', 'active': True},
                {'id': '00000000-0000-0000-0000-000000000032', 'name': 'original-disabled', 'role': 'cashier', 'active': False},
            ])
            before = connection.execute(text('SELECT * FROM employees ORDER BY id')).mappings().all()
        if runtime:
            from app.schema_maintenance import ensure_runtime_schema
            ensure_runtime_schema()
        else:
            upgrade(directory=migrations, revision='20261004_employee_entries')
        with db.engine.connect() as connection:
            after = connection.execute(text('SELECT * FROM employees ORDER BY id')).mappings().all()
            for old, new in zip(before, after, strict=True):
                assert {key: new[key] for key in old} == dict(old)
                assert new['allowed_channels'] == '[]'
                assert new['deleted_at'] is None
            if not runtime:
                assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20261004_employee_entries'
        db.session.remove()
        db.engine.dispose()
