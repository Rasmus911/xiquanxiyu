from decimal import Decimal

import pytest
from sqlalchemy import literal_column, select, text
from sqlalchemy.exc import DatabaseError, LegacyAPIWarning
from sqlalchemy.orm import aliased
from sqlalchemy.orm.exc import ObjectDeletedError

from app.extensions import db
from app.models import Member


def test_authenticated_business_state_exposes_one_current_period(client, admin_session):
    response = client.get('/api/business/state', headers=admin_session['headers'])
    assert response.status_code == 200
    data = response.get_json()['data']
    assert isinstance(data['period_id'], str) and len(data['period_id']) == 36
    assert data['business_revision'] == 0
    assert data['maintenance'] is False
    assert data['owner_reset_allowed'] is False


def next_period():
    from app.models import BusinessPeriod, BusinessStateModel

    period = BusinessPeriod()
    db.session.add(period)
    db.session.flush()
    state = db.session.get(BusinessStateModel, 1)
    state.period_id = period.id
    db.session.commit()
    return period.id


def test_old_members_hidden_from_list_phone_and_cached_id(app):
    old = Member(phone='13800000001', balance=Decimal('17.50'))
    db.session.add(old)
    db.session.commit()
    old_id = old.id
    next_period()
    assert Member.query.all() == []
    assert Member.query.filter_by(phone='13800000001').first() is None
    assert db.session.get(Member, old_id) is None
    with pytest.warns(LegacyAPIWarning):
        assert Member.query.get(old_id) is None
    db.session.add(Member(phone='13800000001'))
    db.session.commit()
    assert Member.query.count() == 1


def test_archive_read_restores_scope_and_rejects_writes(app):
    from app.business_period import archive_read, current_period_id

    old = Member(phone='13800000002')
    db.session.add(old)
    db.session.commit()
    old_period = current_period_id()
    next_period()
    with archive_read(old_period):
        assert Member.query.one().phone == '13800000002'
        old.name = 'forbidden'
        with pytest.raises(ValueError, match='read.only|归档'):
            db.session.flush()
        db.session.rollback()
    assert Member.query.count() == 0


def test_database_rejects_archived_update_and_period_transfer(app):
    from app.business_period import current_period_id

    row = Member(phone='13800000003')
    db.session.add(row)
    db.session.commit()
    old_id, old_period = row.id, current_period_id()
    new_period = next_period()
    for sql, parameters in [
        ('UPDATE members SET name=:name WHERE id=:id', {'name': 'bad', 'id': old_id}),
        ('UPDATE members SET period_id=:period WHERE id=:id', {'period': new_period, 'id': old_id}),
        ('INSERT INTO members (id,phone,balance,is_active,version,created_at,updated_at,period_id) '
         "VALUES ('bad','13800000004',0,1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,:period)", {'period': old_period}),
    ]:
        with db.engine.begin() as connection:
            with pytest.raises(DatabaseError, match='period|归档'):
                connection.execute(text(sql), parameters)


def test_unscoped_core_reads_and_bulk_business_writes_are_rejected(app):
    with pytest.raises(ValueError, match='ORM|scope|经营期'):
        db.session.execute(select(Member.__table__))
    with pytest.raises(ValueError, match='ORM|scope|经营期'):
        db.session.execute(text('SELECT * FROM members'))
    with pytest.raises(ValueError, match='ORM|scope|经营期'):
        Member.query.update({'name': 'bad'})


def test_business_revision_counts_committed_changes_and_rolls_back(app):
    from app.business_period import business_state_data

    assert business_state_data()['business_revision'] == 0
    db.session.add(Member(phone='13800000005'))
    db.session.commit()
    assert business_state_data()['business_revision'] == 1
    db.session.add(Member(phone='13800000006'))
    db.session.flush()
    assert business_state_data()['business_revision'] == 2
    db.session.rollback()
    assert business_state_data()['business_revision'] == 1


def test_archive_context_forbids_direct_sql_writes(app):
    from app.business_period import archive_read
    with archive_read(None):
        with pytest.raises(ValueError, match='read.only'):
            db.session.execute(text("UPDATE system_settings SET description='bad'"))


def test_orm_text_query_cannot_bypass_current_period(app):
    db.session.add(Member(phone='13800000007'))
    db.session.commit()
    next_period()
    with pytest.raises(ValueError, match='ORM|scope'):
        db.session.execute(select(Member).from_statement(text('SELECT * FROM members'))).all()


def test_cross_period_relationship_rejected_before_sql_flush(app, admin_session):
    from app.models import MemberPass
    old = Member(phone='13800000008')
    db.session.add(old)
    db.session.commit()
    old_id = old.id
    next_period()
    db.session.add(MemberPass(member_id=old_id, name='invalid pass', remaining_count=0))
    with pytest.raises(ValueError, match='period|经营期'):
        db.session.flush()
    db.session.rollback()


def test_mixed_core_orm_select_cannot_read_archived_members(app, admin_session):
    from app.models import Employee
    db.session.add(Member(phone='13800000009'))
    db.session.commit()
    next_period()
    with pytest.raises(ValueError, match='ORM|scope'):
        db.session.execute(select(Member.__table__, Employee).join(Employee, db.true())).all()


def test_database_rejects_cross_period_settlement_link(app, admin_session):
    from app.business_period import current_period_id
    from app.models import Employee, Settlement, SettlementVisit, Terminal, Visit, Wristband
    actor, terminal, band = Employee.query.one(), Terminal.query.one(), Wristband.query.first()
    visit = Visit(wristband_id=band.id, opened_by_id=actor.id)
    db.session.add(visit)
    db.session.commit()
    visit_id, band_id, actor_id = visit.id, band.id, actor.id
    next_period()
    new_visit = Visit(wristband_id=band_id, opened_by_id=actor_id)
    settlement = Settlement(number='new', total_amount=0, paid_amount=0, created_by_id=actor_id,
                            terminal_id=terminal.id, idempotency_key='new')
    db.session.add_all([new_visit, settlement])
    db.session.commit()  # The previous period's active band no longer occupies this period.
    with pytest.raises(DatabaseError, match='period'):
        db.session.connection().execute(SettlementVisit.__table__.insert().values(
            settlement_id=settlement.id, visit_id=visit_id, amount=0, period_id=current_period_id()))
    db.session.rollback()


def test_cached_old_entity_cannot_write_or_be_reassigned(app):
    old = Member(phone='13800000010')
    db.session.add(old)
    db.session.commit()
    new_period = next_period()
    old.name = 'bad'
    with pytest.raises(ValueError, match='归档'):
        db.session.flush()
    db.session.rollback()
    old.period_id = new_period
    with pytest.raises(ValueError, match='归属'):
        db.session.flush()
    db.session.rollback()


def test_raw_alias_cannot_smuggle_archived_columns_alongside_current_entity(app):
    db.session.add(Member(phone='13800000011'))
    db.session.commit()
    next_period()
    db.session.add(Member(phone='13800000012'))
    db.session.commit()
    raw = Member.__table__.alias('raw')
    with pytest.raises(ValueError, match='ORM|scope'):
        db.session.execute(select(Member, raw.c.phone).join(raw, db.true())).all()


def test_orm_alias_stays_scoped(app):
    db.session.add(Member(phone='13800000013'))
    db.session.commit()
    next_period()
    db.session.add(Member(phone='13800000014'))
    db.session.commit()
    member = aliased(Member)
    assert db.session.scalars(select(member.phone)).all() == ['13800000014']


def test_expired_current_entity_attributes_reload_after_commit(app):
    row = Member(phone='13800000015', balance=Decimal('12.50'))
    db.session.add(row)
    db.session.commit()
    assert len(row.id) == 36
    assert row.phone == '13800000015'
    db.session.expire(row)
    assert row.balance == Decimal('12.50')


def test_expired_archived_entity_cannot_reload_attributes_outside_archive(app):
    from app.business_period import archive_read, current_period_id
    row = Member(phone='13800000016')
    db.session.add(row)
    db.session.commit()
    old_period = current_period_id()
    next_period()
    with pytest.raises(ObjectDeletedError):
        _ = row.phone
    with archive_read(old_period):
        assert row.phone == '13800000016'
    with pytest.raises(ObjectDeletedError):
        _ = row.phone


@pytest.mark.parametrize('expression_kind', ['core_subquery', 'text', 'literal_column'])
def test_outer_mapped_entity_cannot_authorize_unscoped_inner_read(app, expression_kind):
    db.session.add(Member(phone='OLD'))
    db.session.commit()
    next_period()
    db.session.add(Member(phone='NEW'))
    db.session.commit()
    if expression_kind == 'core_subquery':
        expression = select(Member.__table__.c.phone).where(
            Member.__table__.c.phone == 'OLD').correlate(None).scalar_subquery()
    elif expression_kind == 'text':
        expression = text("(SELECT phone FROM members WHERE phone='OLD')")
    else:
        expression = literal_column("(SELECT phone FROM members WHERE phone='OLD')")
    with pytest.raises(ValueError, match='ORM|scope'):
        db.session.execute(select(Member, expression)).all()


def test_nested_mapped_alias_remains_filtered_to_current_period(app):
    db.session.add(Member(phone='OLD'))
    db.session.commit()
    next_period()
    db.session.add(Member(phone='NEW'))
    db.session.commit()
    inner_member = aliased(Member)
    expression = select(inner_member.phone).where(inner_member.phone == 'OLD').scalar_subquery()
    assert db.session.execute(select(Member.phone, expression)).all() == [('NEW', None)]


def test_mapped_alias_cannot_authorize_a_distinct_raw_table_occurrence(app):
    db.session.add(Member(phone='OLD'))
    db.session.commit()
    next_period()
    db.session.add(Member(phone='NEW'))
    db.session.commit()
    member = aliased(Member)
    with pytest.raises(ValueError, match='ORM|scope'):
        db.session.execute(select(member, Member.__table__.c.phone).join(
            Member.__table__, db.true())).all()
