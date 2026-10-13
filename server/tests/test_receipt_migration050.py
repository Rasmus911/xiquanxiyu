from pathlib import Path

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.config import TestConfig
from app.extensions import db


def test_receipt_migration_is_additive_and_installs_scoped_guards(tmp_path):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'receipts.sqlite').as_posix()}"
    application = create_app(MigrationConfig)
    directory = str(Path(__file__).resolve().parents[1]/'migrations')
    with application.app_context():
        upgrade(directory=directory,revision='20261011_employee_identity')
        from legacy_seed import seed_legacy_defaults
        seed_legacy_defaults()
        with db.engine.connect() as connection:
            before = {name:[dict(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings()]
                      for name in inspect(connection).get_table_names() if name!='alembic_version'}
        upgrade(directory=directory,revision='20261011_service_receipts')
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20261011_service_receipts'
            for name,rows in before.items():
                assert [dict(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings()] == rows
            tables = {'service_print_jobs','service_print_attempts','settlement_print_attempts'}
            assert tables <= set(inspect(connection).get_table_names())
            triggers = {r[0] for r in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")}
            for name in tables:
                assert 'period_'+name+'_insert' in triggers
                assert 'barrier_'+name+'_insert' in triggers
            assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        db.session.remove(); db.engine.dispose()
