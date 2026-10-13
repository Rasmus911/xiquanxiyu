from pathlib import Path
from flask_migrate import upgrade
from sqlalchemy import inspect
from app import create_app
from app.config import TestConfig
from app.extensions import db

def test_manual_inventory_migration_adds_only_nullable_costs_and_empty_evidence(tmp_path):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{(tmp_path/'manual055.sqlite').as_posix()}"
    app=create_app(MigrationConfig);directory=str(Path(__file__).resolve().parents[1]/'migrations')
    with app.app_context():
        upgrade(directory=directory,revision='20261013_wristband_chip')
        with db.engine.connect() as connection:
            assert not {'reference_cost','cost_basis'} & {column['name'] for column in inspect(connection).get_columns('stock_items')}
        with db.engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO stock_items (id,name,category,base_unit,package_unit,units_per_package,package_spec,stock_quantity,low_stock_threshold,unit_cost,is_active,version,created_at,updated_at) VALUES ('retain','保留奶膏','耗材','袋','箱',200,'',800,120,0.6,1,3,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        with db.engine.connect() as connection:
            before={name:[dict(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings()] for name in inspect(connection).get_table_names() if name!='alembic_version'}
        upgrade(directory=directory,revision='20261013_manual_inventory_excel')
        with db.engine.connect() as connection:
            for name,rows in before.items():
                after=[dict(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings()]
                if name=='stock_items':
                    assert all(row.pop('reference_cost') is None and row.pop('cost_basis') is None for row in after)
                assert after==rows
            for name in ('stock_import_pending','stock_import_resolutions'):
                assert connection.exec_driver_sql(f'SELECT count(*) FROM {name}').scalar_one()==0
            assert connection.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        db.session.remove();db.engine.dispose()
