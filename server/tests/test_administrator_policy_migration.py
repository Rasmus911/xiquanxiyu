"""A schema-only upgrade keeps original credentials and existing policy bindings."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask_migrate import upgrade
from sqlalchemy import MetaData, inspect, select, text

from app import create_app
from app.auth_service import hash_password
from app.config import TestConfig
from app.extensions import db
from app.models import AccessPolicyModel, new_uuid


@pytest.mark.parametrize('runtime', [False, True])
def test_migration_preserves_existing_policy_and_employee_activation_and_passwords(tmp_path, runtime):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'admins-upgrade.sqlite').as_posix()}"

    application = create_app(MigrationConfig)
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    with application.app_context():
        upgrade(directory=migrations, revision='20261002_reset_barrier')
        # Older migrations import today's model metadata. Remove the new field
        # only in this disposable database to reproduce the actual old schema.
        with db.engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE access_policies DROP COLUMN administrator_employee_ids')
        assert 'administrator_employee_ids' not in {
            column['name'] for column in inspect(db.engine).get_columns('access_policies')}
        digest = hash_password('migration-test-only-1234')
        # Seed the historical schema without today's Employee mapper, which
        # now includes columns this deliberately old database does not have.
        employees = [SimpleNamespace(id=new_uuid(), username=name, is_active=active)
                     for name, active in [('owner', True), ('mobile1', True), ('mobile2', True), ('disabled', False)]]
        with db.engine.begin() as connection:
            connection.execute(text("""INSERT INTO employees
                (id,created_at,updated_at,version,username,display_name,password_hash,role,
                 is_active,mobile_full_access,session_version,failed_login_attempts)
                VALUES (:id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,:name,'原姓名',:digest,'admin',
                        :active,FALSE,1,0)"""),
                [{'id': row.id, 'name': row.username, 'active': row.is_active, 'digest': digest} for row in employees])
        metadata = MetaData()
        metadata.reflect(bind=db.engine)
        connection = db.session.connection()
        connection.execute(text("""INSERT INTO access_policies
            (id, created_at, updated_at, version, owner_id, mobile_employee_ids, policy_version, is_active)
            VALUES ('old-policy', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, :owner, :mobile, 1, 1)"""),
                           {'owner': employees[0].id, 'mobile': json.dumps([row.id for row in employees[1:3]])})
        db.session.commit()
        with db.engine.connect() as connection:
            before = {name: [dict(row) for row in connection.execute(select(table)).mappings()]
                      for name, table in metadata.tables.items() if name != 'alembic_version'}
        if runtime:
            from app.schema_maintenance import ensure_runtime_schema
            ensure_runtime_schema()
        else:
            upgrade(directory=migrations, revision='20261003_preserve_administrators')
        with db.engine.connect() as connection:
            for name, rows in before.items():
                assert [dict(row) for row in connection.execute(select(metadata.tables[name])).mappings()] == rows
            if not runtime:
                assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == (
                    '20261003_preserve_administrators')
        assert 'administrator_employee_ids' in {
            column['name'] for column in inspect(db.engine).get_columns('access_policies')}
        policy = db.session.get(AccessPolicyModel, 'old-policy')
        assert policy.administrator_employee_ids == []
        assert policy.owner_id == employees[0].id
        assert policy.mobile_employee_ids == [row.id for row in employees[1:3]]
        db.session.remove()
        db.engine.dispose()
