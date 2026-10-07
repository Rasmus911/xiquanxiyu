from datetime import datetime
from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.exc import DatabaseError

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import CatalogItem, OrderItem, Wristband


def test_operational_field_contract():
    assert {'bath_area','is_active'} <= set(Wristband.__table__.columns.keys())
    assert {'reference_code','package_definition'} <= set(CatalogItem.__table__.columns.keys())
    assert {'covered_quantity','package_order_item_id','package_snapshot'} <= set(OrderItem.__table__.columns.keys())


@pytest.mark.parametrize('runtime', [False, True])
@pytest.mark.parametrize('active', [False, True])
def test_structural_migration_preserves_original_money_stock_and_history(tmp_path, runtime, active):
    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'operations.sqlite').as_posix()}"
    application = create_app(Config)
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    with application.app_context():
        upgrade(directory=migrations, revision='20261004_employee_entries')
        metadata = MetaData(); metadata.reflect(bind=db.engine)
        now = datetime(2026,10,4,12)
        def insert(table_name, id_, **values):
            table = metadata.tables[table_name]
            common = dict(id=id_,created_at=now,updated_at=now,version=1)
            db.session.connection().execute(table.insert().values(**{key:value for key,value in {**common,**values}.items() if key in table.c}))
        insert('employees','e',username='original',display_name='原用户',password_hash='opaque',role='admin',
            is_active=True,mobile_full_access=False,session_version=1,failed_login_attempts=0,allowed_channels=[])
        for id_, number in [('m','8001'),('f','9001'),('u','unexpected')]: insert('wristbands',id_,number=number,status='available')
        insert('members','member',phone='13800000001',balance=25,is_active=True)
        insert('catalog_items','water',kind='product',category='饮品',name='水',mobile_scope='rest',price=3,
            is_active=active,stock_tracked=True,stock_quantity=5,low_stock_threshold=0,sort_order=10)
        insert('visits','v',wristband_id='m',opened_by_id='e',status='closed',opened_at=now)
        insert('order_items','line',visit_id='v',catalog_item_id='water',kind='product',name_snapshot='水',
            unit_price=3,quantity=1,total_amount=3,status='active',created_by_id='e')
        from app.audit_service import verify_audit_chain, write_audit
        write_audit('fixture.before_structure', 'visit', 'v', {'amount':'3.00'}, employee_id='e')
        db.session.commit()
        old = {name: [dict(row) for row in db.session.connection().execute(select(metadata.tables[name])).mappings()]
            for name in ('employees','wristbands','members','catalog_items','visits','order_items','audit_logs')}
        db.session.rollback()
        if runtime:
            from app.schema_maintenance import ensure_runtime_schema
            ensure_runtime_schema()
        else: upgrade(directory=migrations)
        with db.engine.connect() as connection:
            for name, rows in old.items():
                if name == 'catalog_items':
                    rows = [{**row, 'low_stock_threshold': row['stock_quantity'] * 15 / 100} for row in rows]
                assert [dict(row) for row in connection.execute(select(metadata.tables[name])).mappings()] == rows
            assert dict(connection.execute(text('SELECT number,bath_area FROM wristbands')).all()) == {'8001':'male','9001':'female','unexpected':'other'}
            assert connection.execute(text('SELECT covered_quantity FROM order_items')).scalar_one() == 0
            assert connection.execute(text('SELECT is_active FROM wristbands WHERE id=\'m\'')).scalar_one() == 1
            master = connection.execute(text("SELECT stock_quantity,base_unit,units_per_package FROM stock_items WHERE legacy_catalog_item_id='water'")).one()
            assert (str(master[0]),master[1],str(master[2])) == ('5','原销售单位','1')
            assert connection.execute(text('SELECT count(*) FROM stock_movements')).scalar_one() == 0
            assert bool(connection.execute(text("SELECT is_active FROM stock_items WHERE legacy_catalog_item_id='water'")).scalar_one()) is active
            assert connection.execute(text('SELECT deleted_at FROM members')).scalar_one() is None
            assert connection.execute(text('SELECT deleted_at FROM catalog_items')).scalar_one() is None
            if not runtime:
                assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20261007_ordering_cost'
        if runtime: ensure_runtime_schema()
        else: upgrade(directory=migrations)
        assert verify_audit_chain() == (True, None)
        db.session.remove(); db.engine.dispose()


def test_package_parent_cannot_cover_another_visit(app, admin_session):
    from app.database_guards import install_database_guards, install_period_guards
    assert 'package_order_item_id' in OrderItem.__table__.columns
    with db.engine.begin() as connection:
        install_database_guards(connection); install_period_guards(connection)
    employee_id = admin_session['login']['employee']['id']
    bands = Wristband.query.limit(2).all()
    from app.models import Visit
    visits = [Visit(wristband_id=band.id,opened_by_id=employee_id) for band in bands]
    db.session.add_all(visits); db.session.flush()
    package = OrderItem(visit_id=visits[0].id,kind='package',name_snapshot='包',unit_price=45,quantity=1,total_amount=45,created_by_id=employee_id)
    db.session.add(package); db.session.flush()
    db.session.add(OrderItem(visit_id=visits[1].id,kind='service',name_snapshot='搓澡',unit_price=10,quantity=1,
        total_amount=0,covered_quantity=1,package_order_item_id=package.id,created_by_id=employee_id))
    with pytest.raises(DatabaseError): db.session.flush()
    db.session.rollback()


@pytest.mark.parametrize('field,value', [('covered_quantity','1'),('package_snapshot',"'{}'"),('package_order_item_id',"'forged'")])
def test_new_fields_of_settled_orders_are_sql_immutable(app, client, admin_session, field, value):
    from app.database_guards import install_database_guards, install_period_guards
    with db.engine.begin() as connection:
        install_database_guards(connection); install_period_guards(connection)
    h = admin_session['headers']
    band = Wristband.query.first()
    visit_id = client.post(f'/api/wristbands/{band.id}/open', headers=h, json={}).get_json()['data']['id']
    service = CatalogItem.query.filter_by(kind='service',is_active=True).first()
    assert client.post(f'/api/visits/{visit_id}/items', headers=h, json={'catalog_item_id':service.id}).status_code == 201
    result = client.post('/api/checkout', headers={**h,'Idempotency-Key':'settled-fields'},
        json={'visit_ids':[visit_id],'payments':[{'method':'cash','amount':str(service.price)}],'idempotency_key':'settled-fields'})
    assert result.status_code == 201
    with db.engine.begin() as connection:
        with pytest.raises(DatabaseError):
            connection.execute(text(f'UPDATE order_items SET {field}={value} WHERE visit_id=:id'), {'id':visit_id})
