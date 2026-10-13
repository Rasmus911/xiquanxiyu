from decimal import Decimal
from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Member
from app.serializers import member_dict

from app.member_cards import normalize_card_uid


@pytest.mark.parametrize('raw, expected', [
    ('315346091\r\n', '315346091'), (' 000315346091\n', '000315346091'),
    ('0' * 64, '0' * 64)])
def test_uid_is_text(raw, expected):
    assert normalize_card_uid(raw) == expected


@pytest.mark.parametrize('raw', ['', '1 2', '１23', '1' * 65, 315346091])
def test_uid_rejects_invalid_input(raw):
    with pytest.raises(ValueError):
        normalize_card_uid(raw)


def card_model():
    from app import models
    assert hasattr(models, 'MemberCardBinding'), 'physical card model must be registered'
    return models.MemberCardBinding


def redemption_model():
    from app import models
    assert hasattr(models, 'SettlementPassRedemption'), 'redemption evidence model must be registered'
    return models.SettlementPassRedemption


@pytest.fixture()
def card_context(app, admin_session):
    from app.models import Employee, Terminal
    members = [Member(phone='13800000001', name='完整姓名'), Member(phone='13800000002')]
    db.session.add_all(members)
    db.session.commit()
    return {'members': members, 'actor': Employee.query.one().id, 'terminal': Terminal.query.one().id}


def bind(context, member=0, uid='000315346091', **kwargs):
    row = card_model()(member_id=context['members'][member].id, card_uid=uid,
        created_by=context['actor'], terminal_id=context['terminal'], **kwargs)
    db.session.add(row)
    db.session.commit()
    return row


def test_members_without_phone_store_null_and_serialize_empty_string(app):
    first = Member(phone=None, name='李完整名')
    second = Member(phone=None)
    db.session.add_all([first, second])
    db.session.commit()
    assert Member.query.count() == 2
    assert first.phone is None and second.phone is None
    assert member_dict(first)['phone'] == ''
    assert member_dict(first, include_phone=False)['phone'] == ''


def test_real_phone_remains_unique_in_current_period(app):
    db.session.add(Member(phone='13800000001'))
    db.session.commit()
    db.session.add(Member(phone='13800000001'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_holder_surname_is_independent_and_serializer_selects_only_active_card(card_context):
    first = card_context['members'][0]
    first.holder_surname = '李'
    old = bind(card_context)
    old.is_active = False
    from app.models import utcnow
    old.revoked_at = utcnow()
    db.session.commit()
    assert member_dict(first)['card_binding'] is None
    active = bind(card_context, uid='315346092')
    result = member_dict(first)
    assert result['name'] == '完整姓名'
    assert result['holder_surname'] == '李'
    assert result['card_binding']['id'] == active.id
    assert result['card_binding']['card_uid'] == '315346092'
    assert result['card_binding']['is_active'] is True


def test_card_uid_cannot_be_reassigned_even_after_revocation(card_context):
    old = bind(card_context)
    old.is_active = False
    from app.models import utcnow
    old.revoked_at = utcnow()
    db.session.commit()
    db.session.add(card_model()(member_id=card_context['members'][1].id, card_uid='000315346091',
        created_by=card_context['actor'], terminal_id=card_context['terminal']))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_member_cannot_have_two_active_cards(card_context):
    bind(card_context)
    db.session.add(card_model()(member_id=card_context['members'][0].id, card_uid='315346092',
        created_by=card_context['actor'], terminal_id=card_context['terminal']))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.parametrize('column,value', [
    ('id', 'changed'), ('member_id', 'changed'), ('period_id', 'changed'),
    ('card_uid', '315346093'), ('created_by', 'changed'), ('terminal_id', 'changed'),
    ('created_at', '2026-01-01')])
def test_database_rejects_card_identity_changes(card_context, column, value):
    # Use valid referenced rows: a missing identity guard must not be hidden by FK errors.
    from app.models import BusinessPeriod, Employee, Terminal
    if column == 'member_id':
        value = card_context['members'][1].id
    elif column == 'created_by':
        actor = Employee(username='second-actor', display_name='第二员工', role='cashier', password_hash='fixture-only')
        db.session.add(actor)
        db.session.commit()
        value = actor.id
    elif column == 'terminal_id':
        terminal = Terminal(code='SECOND-051', name='第二终端')
        db.session.add(terminal)
        db.session.commit()
        value = terminal.id
    elif column == 'period_id':
        period = BusinessPeriod()
        db.session.add(period)
        db.session.commit()
        value = period.id
    row = bind(card_context)
    with pytest.raises(DatabaseError):
        db.session.connection().execute(text(f'UPDATE member_card_bindings SET {column}=:value WHERE id=:id'),
            {'value': value, 'id': row.id})
    db.session.rollback()


def test_card_can_be_revoked_and_linked_to_replacement_but_never_reactivated_or_deleted(card_context):
    from app.models import utcnow
    old = bind(card_context)
    old.is_active = False
    old.revoked_at = utcnow()
    old.version += 1
    db.session.commit()
    new = bind(card_context, uid='315346092')
    old.replaced_by_id = new.id
    db.session.commit()
    assert old.replaced_by_id == new.id
    new.is_active = False
    new.revoked_at = utcnow()
    db.session.commit()
    for sql in ['UPDATE member_card_bindings SET is_active=1 WHERE id=:id',
                'DELETE FROM member_card_bindings WHERE id=:id']:
        with pytest.raises(DatabaseError):
            db.session.connection().execute(text(sql), {'id': old.id})
        db.session.rollback()


def test_serializer_keeps_existing_phone_mask(card_context):
    row = card_context['members'][0]
    assert member_dict(row)['phone'] == '13800000001'
    assert member_dict(row, include_phone=False)['phone'] == '138****0001'


def next_period():
    from app.models import BusinessPeriod, BusinessStateModel
    row = BusinessPeriod()
    db.session.add(row)
    db.session.flush()
    db.session.get(BusinessStateModel, 1).period_id = row.id
    db.session.commit()
    return row.id


def test_card_lookup_is_scoped_and_cross_period_member_link_is_rejected(card_context):
    from app.business_period import archive_read
    row = bind(card_context)
    old_id, old_member, old_period = row.id, row.member_id, row.period_id
    new_period = next_period()
    assert card_model().query.filter_by(card_uid='000315346091').first() is None
    assert db.session.get(card_model(), old_id) is None
    with archive_read(old_period):
        assert card_model().query.one().id == old_id
    with pytest.raises(DatabaseError, match='period'):
        db.session.connection().execute(card_model().__table__.insert().values(
            member_id=old_member, card_uid='315346092', created_by=card_context['actor'],
            terminal_id=card_context['terminal'], period_id=new_period))
    db.session.rollback()


@pytest.fixture()
def redemption(card_context):
    from app.models import MemberPass, OrderItem, Settlement, Visit, Wristband
    visit = Visit(wristband_id=Wristband.query.first().id, opened_by_id=card_context['actor'])
    member_pass = MemberPass(member_id=card_context['members'][0].id, name='十次卡', remaining_count=10)
    settlement = Settlement(number='CARD-051', total_amount=30, paid_amount=0,
        created_by_id=card_context['actor'], terminal_id=card_context['terminal'], idempotency_key='CARD-051')
    db.session.add_all([visit, member_pass, settlement])
    db.session.flush()
    ticket = OrderItem(visit_id=visit.id, kind='ticket', name_snapshot='门票', unit_price=30,
        total_amount=30, created_by_id=card_context['actor'])
    db.session.add(ticket)
    db.session.flush()
    row = redemption_model()(settlement_id=settlement.id, visit_id=visit.id, order_item_id=ticket.id,
        member_pass_id=member_pass.id, count=1, amount=Decimal('30.00'))
    db.session.add(row)
    db.session.commit()
    return row


@pytest.mark.parametrize('sql', [
    'UPDATE settlement_pass_redemptions SET amount=0 WHERE id=:id',
    'UPDATE settlement_pass_redemptions SET count=2 WHERE id=:id',
    'DELETE FROM settlement_pass_redemptions WHERE id=:id'])
def test_redemption_evidence_cannot_be_changed_or_deleted(redemption, sql):
    row_id = redemption.id
    with pytest.raises(DatabaseError, match='immutable'):
        db.session.connection().execute(text(sql), {'id': row_id})
    db.session.rollback()
    assert redemption_model().query.one().amount == Decimal('30.00')


def test_redemption_lookup_is_scoped_and_cross_period_links_are_rejected(redemption):
    ids = {name: getattr(redemption, name) for name in
        ('settlement_id', 'visit_id', 'order_item_id', 'member_pass_id')}
    next_period()
    assert redemption_model().query.all() == []
    from app.business_period import current_period_id
    with pytest.raises(DatabaseError, match='period'):
        db.session.connection().execute(redemption_model().__table__.insert().values(
            **ids, count=1, amount=30, period_id=current_period_id()))
    db.session.rollback()


def test_card_binding_uses_immutable_employee_identity(card_context):
    from app.models import Employee, EmployeeIdentity
    row = bind(card_context)
    actor = Employee.query.one()
    db.session.delete(actor)
    db.session.commit()
    assert db.session.get(EmployeeIdentity, row.created_by) is not None
    assert card_model().query.one().card_uid == '000315346091'


def test_maintenance_blocks_new_table_writes_at_sql_level(redemption):
    from app.models import BusinessStateModel
    state = db.session.get(BusinessStateModel, 1)
    state.maintenance = True
    db.session.commit()
    for table in ('member_card_bindings', 'settlement_pass_redemptions'):
        with pytest.raises(DatabaseError, match='BUSINESS_MAINTENANCE'):
            with db.engine.begin() as connection:
                connection.execute(text(f'INSERT INTO {table} (id) VALUES (:id)'), {'id': 'maintenance-test'})


def test_migration_preserves_existing_values_and_installs_new_guards(tmp_path):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'cards.sqlite').as_posix()}"
    application = create_app(MigrationConfig)
    directory = str(Path(__file__).resolve().parents[1] / 'migrations')
    with application.app_context():
        upgrade(directory=directory, revision='20261011_service_receipts')
        with db.engine.begin() as connection:
            connection.execute(text("""INSERT INTO members
                (id,phone,name,balance,is_active,version,created_at,updated_at,period_id)
                SELECT 'original','13800000001','原姓名',127.50,1,3,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,period_id
                FROM business_state WHERE id=1"""))
        from app.models import Employee, MemberPass, PassLedger, Terminal
        employee = Employee(username='migration-actor', display_name='原员工', role='cashier', password_hash='fixture-only')
        terminal = Terminal(code='MIGRATION-051', name='原终端')
        member_pass = MemberPass(member_id='original', name='原十次卡', remaining_count=7)
        db.session.add_all([employee, terminal, member_pass])
        db.session.flush()
        db.session.add(PassLedger(member_pass_id=member_pass.id, delta=7, balance_after=7,
            entry_type='issue', amount_paid=Decimal('210.00'), payment_method='cash', operator_id=employee.id))
        db.session.commit()
        pass_id, employee_id, terminal_id = member_pass.id, employee.id, terminal.id
        with db.engine.connect() as connection:
            before = {name: [dict(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{name}"').mappings()]
                for name in inspect(connection).get_table_names() if name != 'alembic_version'}
        upgrade(directory=directory, revision='20261012_physical_membership')
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20261012_physical_membership'
            for name, rows in before.items():
                columns = ','.join('"'+c+'"' for c in (rows[0] if rows else [])) or '*'
                assert [dict(row) for row in connection.exec_driver_sql(f'SELECT {columns} FROM "{name}"').mappings()] == rows
            assert next(c for c in inspect(connection).get_columns('members') if c['name']=='phone')['nullable']
            triggers = {r[0] for r in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")}
            for name in ('member_card_bindings', 'settlement_pass_redemptions'):
                assert 'period_'+name+'_insert' in triggers
                assert 'barrier_'+name+'_insert' in triggers
            assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        db.session.add_all([Member(phone=None), Member(phone=None)])
        db.session.commit()
        assert Member.query.count() == 3
        assert db.session.get(Member, 'original').balance == Decimal('127.50')
        assert db.session.get(MemberPass, pass_id).remaining_count == 7
        db.session.add(card_model()(member_id='original', card_uid='000315346091',
            created_by=employee_id, terminal_id=terminal_id))
        db.session.commit()
        with pytest.raises(DatabaseError, match='immutable'):
            db.session.connection().execute(text("UPDATE member_card_bindings SET card_uid='315346093'"))
        db.session.rollback()
        with pytest.raises(DatabaseError, match='immutable'):
            db.session.connection().execute(text('UPDATE pass_ledgers SET amount_paid=0'))
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
