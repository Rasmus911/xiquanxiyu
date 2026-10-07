from datetime import datetime
from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.exc import DatabaseError

from app import create_app
from app.audit_service import verify_audit_chain, write_audit
from app.config import TestConfig
from app.extensions import db


@pytest.mark.parametrize('runtime', [False, True])
def test_upgrade_keeps_all_original_values_and_protects_archives(tmp_path, runtime):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'period-upgrade.db').as_posix()}"

    application = create_app(MigrationConfig)
    migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
    with application.app_context():
        upgrade(directory=migrations, revision='20260930_security_evidence')
        metadata = MetaData()
        metadata.reflect(bind=db.engine)
        now = datetime(2026, 9, 30, 12)

        def insert(table_name, **values):
            table = metadata.tables[table_name]
            values = {'id': table_name, 'created_at': now, 'updated_at': now, 'version': 1, **values}
            values = {k: v for k, v in values.items() if k in table.c}
            db.session.connection().execute(table.insert().values(**values))

        insert('employees', username='legacy', display_name='legacy', password_hash='hash',
               role='admin', is_active=True, mobile_full_access=False, session_version=1, failed_login_attempts=0)
        insert('terminals', code='legacy', name='legacy', is_active=True)
        insert('wristbands', number='8001', status='in_use')
        insert('members', phone='13800000001', balance=25, is_active=True)
        insert('visits', wristband_id='wristbands', member_id='members', opened_by_id='employees',
               status='closed', opened_at=now)
        insert('order_items', visit_id='visits', kind='service', name_snapshot='bath', unit_price=20,
               quantity=1, total_amount=20, status='active', created_by_id='employees')
        insert('shifts', employee_id='employees', terminal_id='terminals', status='open', opening_cash=0, opened_at=now)
        insert('settlements', number='legacy', status='completed', total_amount=20, paid_amount=20,
               created_by_id='employees', terminal_id='terminals', shift_id='shifts', member_id='members',
               idempotency_key='legacy-settlement', completed_at=now)
        insert('settlement_visits', settlement_id='settlements', visit_id='visits', amount=20)
        insert('payments', settlement_id='settlements', shift_id='shifts', method='cash', amount=20, kind='payment')
        insert('stored_value_ledgers', member_id='members', amount=25, balance_after=25,
               entry_type='recharge', payment_method='cash', operator_id='employees')
        insert('member_passes', member_id='members', name='bath pass', remaining_count=3, is_active=True)
        insert('pass_ledgers', member_pass_id='member_passes', delta=3, balance_after=3,
               entry_type='purchase', amount_paid=30, payment_method='cash', operator_id='employees')
        insert('print_jobs', settlement_id='settlements', terminal_id='terminals', status='pending', attempts=0)
        insert('catalog_items', name='water', kind='product', category='drink', price=3, is_active=True,
               stock_tracked=True, stock_quantity=5, low_stock_threshold=0, sort_order=1, mobile_scope='rest')
        insert('inventory_movements', catalog_item_id='catalog_items', movement_type='in', quantity=5,
               balance_after=5, operator_id='employees')
        insert('idempotency_records', key='legacy', endpoint='legacy', response_status=200, response_body={})
        db.session.commit()
        with application.test_request_context('/migration-test'):
            write_audit('legacy.period', 'test', None, {})
            db.session.commit()
        with db.engine.connect() as connection:
            before = {name: [dict(row) for row in connection.execute(select(table)).mappings()]
                      for name, table in metadata.tables.items() if name != 'alembic_version'}
        if runtime:
            from app.schema_maintenance import ensure_runtime_schema
            ensure_runtime_schema()
        else:
            upgrade(directory=migrations)
        assert 'business_state' in inspect(db.engine).get_table_names()
        with db.engine.connect() as connection:
            for name, rows in before.items():
                if name == 'catalog_items':
                    # This release changes only the approved alert, not stock or history.
                    rows = [{**row, 'low_stock_threshold': row['stock_quantity'] * 15 / 100} for row in rows]
                assert [dict(row) for row in connection.execute(select(metadata.tables[name])).mappings()] == rows
            # The stock master and mapped catalog alert each advance the write barrier.
            assert connection.execute(text('SELECT business_revision FROM business_state')).scalar_one() == 2
        assert verify_audit_chain() == (True, None)
        from app.business_period import archive_read, current_period_id
        from app.financial_integrity import check_financial_integrity
        from app.models import BusinessPeriod, BusinessStateModel, Member, PeriodMixin
        old_period = current_period_id()
        assert check_financial_integrity()['valid'] is True
        period = BusinessPeriod()
        db.session.add(period)
        db.session.flush()
        db.session.get(BusinessStateModel, 1).period_id = period.id
        db.session.commit()
        assert Member.query.count() == 0
        for mapper in db.Model.registry.mappers:
            model = mapper.class_
            if not issubclass(model, PeriodMixin):
                continue
            assert db.session.query(model).count() == 0
            with archive_read(old_period):
                assert db.session.query(model).count() == (0 if model.__tablename__ in {'stock_movements','order_stock_consumptions'} else 1)
        db.session.add(Member(phone='13800000001'))
        db.session.commit()
        assert check_financial_integrity()['valid'] is True
        assert check_financial_integrity(period_id=old_period)['valid'] is True
        with db.engine.begin() as connection:
            for statement in ("UPDATE members SET balance=0 WHERE id='members'",
                              "UPDATE audit_logs SET current_hash='bad'", 'DELETE FROM payments',
                              'DELETE FROM pass_ledgers'):
                with pytest.raises(DatabaseError):
                    connection.execute(text(statement))
        # Runtime compatibility is repeatable and must never switch/reset periods.
        from app.schema_maintenance import ensure_runtime_schema
        active_period = current_period_id()
        ensure_runtime_schema()
        assert current_period_id() == active_period
        assert Member.query.count() == 1
        db.session.remove()
        db.engine.dispose()
