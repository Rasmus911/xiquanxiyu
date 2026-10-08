"""Additive authorization migration preserves old rows and installs SQL guards."""
from pathlib import Path

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.config import TestConfig
from app.extensions import db


def test_registration_migration_preserves_existing_data_and_guards(tmp_path):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'registration.sqlite').as_posix()}"

    application = create_app(MigrationConfig)
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    with application.app_context():
        upgrade(directory=migrations, revision='20261007_ordering_cost')
        from legacy_seed import seed_legacy_defaults
        from app.models import (Employee, Member, MemberPass, PassLedger, StoredValueLedger,
                                StockItem, Visit, Wristband, CatalogItem, OrderItem)
        from app.audit_service import write_audit
        seed_legacy_defaults()
        employee = Employee(username='migration-existing', display_name='既有员工',
            password_hash='original-opaque-argon2-hash', role='cashier', session_version=7,
            allowed_channels=['desktop'])
        member = Member(phone='13900001234', name='隔离会员', balance=188)
        stock = StockItem(name='隔离库存', base_unit='瓶', stock_quantity=12, unit_cost=3)
        db.session.add_all([employee, member, stock])
        db.session.flush()
        member_pass = MemberPass(member_id=member.id, name='隔离次卡', remaining_count=8)
        visit = Visit(wristband_id=Wristband.query.first().id, member_id=member.id, opened_by_id=employee.id)
        db.session.add_all([member_pass, visit])
        db.session.flush()
        db.session.add_all([
            StoredValueLedger(member_id=member.id, amount=188, balance_after=188,
                entry_type='recharge', operator_id=employee.id),
            PassLedger(member_pass_id=member_pass.id, delta=8, balance_after=8,
                entry_type='issue', amount_paid=200, operator_id=employee.id),
            OrderItem(visit_id=visit.id, catalog_item_id=CatalogItem.query.filter_by(kind='service').first().id,
                kind='service', name_snapshot='既有订单项目', unit_price=30, quantity=2,
                total_amount=60, created_by_id=employee.id),
        ])
        write_audit('fixture.pre_migration', 'employee', employee.id, {'isolated': True}, employee_id=employee.id)
        db.session.commit()
        with db.engine.begin() as connection:
            # All preexisting tables, not just employees, must be preserved.
            before = {name: connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings().all()
                for name in inspect(connection).get_table_names() if name != 'alembic_version'}
            assert not {'registration_token_state', 'registration_rate_limits', 'registration_receipts',
                        'registration_token_views'} & before.keys()
        upgrade(directory=migrations, revision='20261008_registration_token')
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20261008_registration_token'
            for name, rows in before.items():
                assert connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings().all() == rows
            names = set(inspect(connection).get_table_names())
            assert {'registration_token_state', 'registration_rate_limits', 'registration_receipts', 'registration_token_views'} <= names
            triggers = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")}
            for table in ('registration_token_state', 'registration_rate_limits', 'registration_receipts', 'registration_token_views'):
                assert f'barrier_{table}_insert' in triggers
            assert 'protect_registration_receipts_update' in triggers
            assert 'protect_registration_token_views_delete' in triggers
        db.session.remove()
        db.engine.dispose()


def test_ordinary_startup_requires_explicit_migration(tmp_path):
    from app.config import Config

    class StartupConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'uninitialized.sqlite').as_posix()}"
        AUTO_CREATE_DB = Config.AUTO_CREATE_DB

    application = create_app(StartupConfig)
    with application.app_context():
        assert inspect(db.engine).get_table_names() == []
        db.session.remove()
        db.engine.dispose()
