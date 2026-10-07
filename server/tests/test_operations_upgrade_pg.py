"""Opt-in integration test: only a new, local, disposable PG17 database.

Never uses DATABASE_URL or .env. Running this requires explicit acknowledgement
and an isolated cluster with no existing xiquan_app role.
"""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DatabaseError

from app import create_app
from app.business_barrier import BARRIER_KEY, exclusive_barrier
from app.config import TestConfig
from app.extensions import db
from app.operations_upgrade import _require_owner


def test_pg_actual_owner_and_runtime_exclusive_lock_boundaries():
    configured = os.getenv('XIQUAN_TEST_POSTGRES_URL')
    if not configured or os.getenv('XIQUAN_ALLOW_PG_TESTS') != '1':
        pytest.skip('Needs explicitly acknowledged disposable local PostgreSQL 17, not SQLite')
    url = make_url(configured)
    if (url.host not in {'localhost','127.0.0.1','::1'} or not url.database
            or not url.database.startswith('xiquan_ops_test_') or not url.drivername.startswith('postgresql')):
        pytest.fail('Refuse nonlocal or non-disposable database')
    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = configured
    app = create_app(Config)
    role_created = False
    password = 'fixture-'+uuid4().hex
    with app.app_context():
        if inspect(db.engine).get_table_names(): pytest.fail('Refuse a nonempty database')
        with db.engine.connect() as connection:
            if int(connection.exec_driver_sql('SHOW server_version_num').scalar_one())//10000 != 17:
                pytest.fail('PostgreSQL 17 required')
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname='xiquan_app'")).first():
                pytest.fail('Refuse an existing runtime role; use a separate cluster')
        db.create_all()
        from app.seed import seed_defaults
        seed_defaults()
        runtime = None
        try:
            with db.engine.begin() as owner:
                owner.execute(text('CREATE ROLE xiquan_app LOGIN PASSWORD :password'), {'password':password})
                role_created = True
                owner.exec_driver_sql('GRANT USAGE ON SCHEMA public TO xiquan_app')
                owner.exec_driver_sql('GRANT SELECT ON ALL TABLES IN SCHEMA public TO xiquan_app')
                owner.exec_driver_sql('GRANT UPDATE (note) ON wristbands TO xiquan_app')
            with db.engine.connect() as owner:
                _require_owner(owner)
                with exclusive_barrier(owner, 'operations-test'):
                    owner.exec_driver_sql("UPDATE business_state SET maintenance=true, maintenance_reset_id='operations-test' WHERE id=1")
                    owner.exec_driver_sql("UPDATE wristbands SET note='owner-maintenance' WHERE number='001'")
                    owner.commit()
            runtime = create_engine(url.set(username='xiquan_app',password=password))
            with runtime.connect() as connection:
                with pytest.raises(ValueError): _require_owner(connection)
                connection.rollback()
                connection.exec_driver_sql("SELECT set_config('xiquan.reset_task_id','operations-test',false)")
                connection.exec_driver_sql(f'SELECT pg_advisory_lock({BARRIER_KEY})')
                connection.commit()
                with pytest.raises(DatabaseError):
                    connection.exec_driver_sql("UPDATE wristbands SET note='forged' WHERE number='001'")
                connection.rollback()
                connection.exec_driver_sql(f'SELECT pg_advisory_unlock({BARRIER_KEY})')
                connection.commit()
            with db.engine.connect() as owner:
                assert owner.exec_driver_sql("SELECT note FROM wristbands WHERE number='001'").scalar_one()=='owner-maintenance'
                with exclusive_barrier(owner, 'operations-test'):
                    owner.exec_driver_sql('UPDATE business_state SET maintenance=false, maintenance_reset_id=NULL WHERE id=1')
                    owner.commit()
        finally:
            if runtime: runtime.dispose()
            db.session.remove()
            if role_created:
                with db.engine.begin() as connection:
                    connection.exec_driver_sql('DROP OWNED BY xiquan_app')
                    connection.exec_driver_sql('DROP ROLE xiquan_app')
            db.drop_all()
            db.engine.dispose()
