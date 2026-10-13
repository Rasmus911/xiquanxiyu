from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.extensions import db
from app.models import BusinessStateModel, PrintJob, utcnow
from app.receipt_models import ServicePrintAttempt, ServicePrintJob, SettlementPrintAttempt
from app.receipt_retention import business_day_bounds, cleanup_expired_receipts_with_owner
from receipt_fixture050 import order, settle


def seed_expired(result, settlement, count=1):
    cutoff = business_day_bounds(utcnow())[0]
    job = db.session.get(ServicePrintJob,result['response']['meta']['service_print_job']['id'])
    period = job.period_id
    for index in range(count):
        old = ServicePrintJob(visit_id=job.visit_id,terminal_id=job.terminal_id,employee_id=job.employee_id,
            submission_key='expired-'+str(index),bath_area=job.bath_area,snapshot=job.snapshot,
            created_at=cutoff-timedelta(seconds=1))
        db.session.add(old); db.session.flush()
        db.session.add(ServicePrintAttempt(job_id=old.id,request_key='expired-attempt-'+str(index),
            employee_id=job.employee_id,terminal_id=job.terminal_id,mode='manual'))
    old_settlement = PrintJob(settlement_id=settlement,terminal_id=job.terminal_id,
        created_at=cutoff-timedelta(days=3))
    db.session.add(old_settlement); db.session.flush()
    db.session.add(SettlementPrintAttempt(job_id=old_settlement.id,request_key='settlement-expired',
        employee_id=job.employee_id,terminal_id=job.terminal_id,mode='manual'))
    db.session.commit()
    return cutoff,period,job.id


def test_cleanup_batches_all_periods_and_preserves_every_non_receipt_row(app,client,strict_owner_session,desktop050_employee_session):
    result = order(client,strict_owner_session,desktop050_employee_session)
    settlement = settle(client,strict_owner_session,result['visit'])
    cutoff,period,retained = seed_expired(result,settlement,102)
    from test_business_period import next_period
    next_period(); db.session.remove()
    receipt_tables = {'service_print_jobs','print_jobs','service_print_attempts','settlement_print_attempts','business_state'}
    with db.engine.connect() as connection:
        before = {name:connection.exec_driver_sql('SELECT * FROM "'+name+'" ORDER BY 1').all()
            for name in db.metadata.tables if name not in receipt_tables}
        connection.rollback()
        one = cleanup_expired_receipts_with_owner(connection,cutoff,batch_limit=100)
        assert one == {'order_jobs':100,'settlement_jobs':1}
        two = cleanup_expired_receipts_with_owner(connection,cutoff,batch_limit=100)
        assert two == {'order_jobs':2,'settlement_jobs':0}
        assert cleanup_expired_receipts_with_owner(connection,cutoff) == {'order_jobs':0,'settlement_jobs':0}
        assert connection.exec_driver_sql('SELECT id FROM service_print_jobs').scalars().all() == [retained]
        assert connection.exec_driver_sql('SELECT count(*) FROM service_print_attempts').scalar_one() == 0
        assert connection.exec_driver_sql('SELECT count(*) FROM print_jobs').scalar_one() == 1
        assert connection.exec_driver_sql('SELECT count(*) FROM settlement_print_attempts').scalar_one() == 0
        after = {name:connection.exec_driver_sql('SELECT * FROM "'+name+'" ORDER BY 1').all()
            for name in before}
        assert before == after


def test_cleanup_rejects_http_owner_claim_and_raw_delete(app,client,strict_owner_session,desktop050_employee_session):
    result = order(client,strict_owner_session,desktop050_employee_session)
    settlement = settle(client,strict_owner_session,result['visit'])
    cutoff,_,retained = seed_expired(result,settlement)
    db.session.remove()
    with db.engine.connect() as connection:
        with pytest.raises(DatabaseError,match='receipt'):
            connection.exec_driver_sql('DELETE FROM service_print_jobs WHERE id=?',(retained,))
        connection.rollback()
        with app.test_request_context('/api/pretend-owner'):
            with pytest.raises(ValueError,match='HTTP'):
                cleanup_expired_receipts_with_owner(connection,cutoff)


def test_cleanup_never_takes_over_active_maintenance(app,client,strict_owner_session,desktop050_employee_session):
    result = order(client,strict_owner_session,desktop050_employee_session)
    settlement = settle(client,strict_owner_session,result['visit'])
    cutoff,_,_ = seed_expired(result,settlement)
    state = db.session.get(BusinessStateModel,1)
    state.maintenance=True; state.maintenance_reset_id='another-owner'; db.session.commit(); db.session.remove()
    with db.engine.connect() as connection:
        assert cleanup_expired_receipts_with_owner(connection,cutoff) == {'order_jobs':0,'settlement_jobs':0}
        assert connection.exec_driver_sql('SELECT maintenance_reset_id FROM business_state').scalar_one()=='another-owner'
        assert connection.exec_driver_sql('SELECT count(*) FROM service_print_jobs').scalar_one()==2


def test_snapshot_and_identity_cannot_be_rewritten_to_extend_receipt_lifetime(app,client,strict_owner_session,desktop050_employee_session):
    result = order(client,strict_owner_session,desktop050_employee_session)
    job_id=result['response']['meta']['service_print_job']['id']; db.session.remove()
    for sql in ["UPDATE service_print_jobs SET snapshot='{}' WHERE id=:id",
                "UPDATE service_print_jobs SET created_at='2099-01-01' WHERE id=:id",
                "UPDATE service_print_jobs SET bath_area='female' WHERE id=:id"]:
        with db.engine.begin() as connection:
            with pytest.raises(DatabaseError,match='receipt'):
                connection.execute(text(sql),{'id':job_id})


def test_public_api_without_owner_credentials_does_not_start_an_owner_worker(app,monkeypatch):
    from app.receipt_retention import start_receipt_cleanup
    from app.extensions import socketio
    app.config.update(TESTING=False,MAINTENANCE_PROCESS=False,MAINTENANCE_DATABASE_URL='')
    calls=[]
    monkeypatch.setattr(socketio,'start_background_task',lambda target:calls.append(target))
    start_receipt_cleanup(app)
    assert calls==[]
