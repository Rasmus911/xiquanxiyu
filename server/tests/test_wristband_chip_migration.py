from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import BusinessPeriod, BusinessStateModel, WristbandChipBinding, WristbandScanSession


def test_additive_chip_migration_keeps_all_existing_values(tmp_path):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'reader.sqlite').as_posix()}"
    application = create_app(MigrationConfig)
    directory = str(Path(__file__).resolve().parents[1] / 'migrations')
    with application.app_context():
        upgrade(directory=directory, revision='20261012_physical_membership')
        with db.engine.begin() as connection:
            connection.exec_driver_sql("""INSERT INTO members
                (id,phone,name,balance,is_active,version,created_at,updated_at,period_id)
                SELECT 'retained','13800000001','retained',127.50,1,3,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,period_id
                FROM business_state WHERE id=1""")
        with db.engine.connect() as connection:
            before = {name: [dict(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings()]
                for name in inspect(connection).get_table_names() if name != 'alembic_version'}
        upgrade(directory=directory, revision='20261013_wristband_chip')
        with db.engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() == '20261013_wristband_chip'
            for name, rows in before.items():
                assert [dict(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings()] == rows
            assert {'wristband_chip_bindings','wristband_scan_sessions'} <= set(inspect(connection).get_table_names())
        db.session.remove()


def test_chip_binding_has_database_uniqueness(client, formal_catalog, strict_owner_session):
    from test_wristband_reader import band, bind
    assert bind(client, strict_owner_session).status_code == 200
    original = WristbandChipBinding.query.one()
    second = WristbandChipBinding(wristband_id=band('051').id, chip_uid=original.chip_uid,
        changed_by_id=original.changed_by_id, changed_terminal_id=original.changed_terminal_id)
    db.session.add(second)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_binding_persists_across_period_but_old_receiving_session_is_hidden(client, formal_catalog, strict_owner_session):
    from test_wristband_reader import bind
    assert bind(client, strict_owner_session).status_code == 200
    response = client.post('/api/wristband-reader/scan', headers=strict_owner_session['headers'],
        json={'chip_uid':'000315346091','link_mode':True,'idempotency_key':'period-bound-scan'})
    assert response.status_code == 200
    identifier = response.json['data']['session']['id']
    period=BusinessPeriod();db.session.add(period);db.session.flush()
    db.session.get(BusinessStateModel,1).period_id=period.id;db.session.commit()
    assert WristbandChipBinding.query.one().chip_uid == '000315346091'
    assert db.session.get(WristbandScanSession,identifier) is None


def test_chip_tables_are_blocked_by_database_maintenance(client, formal_catalog, strict_owner_session):
    state=db.session.get(BusinessStateModel,1);state.maintenance=True;db.session.commit()
    for table in ('wristband_chip_bindings','wristband_scan_sessions'):
        with pytest.raises(DatabaseError,match='BUSINESS_MAINTENANCE'):
            with db.engine.begin() as connection:
                connection.execute(text(f'INSERT INTO {table} (id) VALUES (:id)'),{'id':'blocked'})
