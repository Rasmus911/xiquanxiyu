"""Beijing natural days, with UTC storage and half-open validity bounds."""
from datetime import datetime, timedelta, timezone

from .api.errors import ApiError

BEIJING = timezone(timedelta(hours=8))


def as_utc(value):
    # SQLite removes tzinfo from UTC database timestamps.
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(timezone.utc)


def business_day_bounds(now):
    local = as_utc(now).astimezone(BEIJING)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start+timedelta(days=1)).astimezone(timezone.utc)


def next_midnight(created_at):
    return business_day_bounds(created_at)[1]


def require_current_receipt(job, now=None):
    now = as_utc(now or datetime.now(timezone.utc))
    start,end = business_day_bounds(now)
    if not start <= as_utc(job.created_at) < end:
        raise ApiError('该小票已超过当日补打时间', 410, 'RECEIPT_EXPIRED')


def cleanup_expired_receipts_with_owner(connection, now=None, batch_limit=100):
    """A short, exclusive transaction; no reset/maintenance takeover or global bypass."""
    from flask import has_request_context
    from sqlalchemy import select
    from .business_barrier import BARRIER_KEY
    from .models import BusinessStateModel, PrintJob, ResetTaskModel
    from .operations_upgrade import _require_owner
    from .receipt_models import ServicePrintJob, ServicePrintAttempt, SettlementPrintAttempt
    if has_request_context(): raise ValueError('Receipt cleanup cannot run through HTTP')
    if type(batch_limit) is not int or not 1 <= batch_limit <= 100: raise ValueError('Invalid receipt batch limit')
    if connection.in_transaction(): raise ValueError('Receipt cleanup requires a fresh owner connection transaction')
    _require_owner(connection); connection.rollback()
    cutoff = business_day_bounds(now or datetime.now(timezone.utc))[0]
    result = {'order_jobs':0,'settlement_jobs':0}
    postgres = connection.dialect.name=='postgresql'
    locked = False
    try:
        if postgres:
            locked = connection.exec_driver_sql(f'SELECT pg_try_advisory_lock({BARRIER_KEY})').scalar_one()
            connection.commit()
            if not locked: return result
            connection.exec_driver_sql("SET LOCAL lock_timeout='3s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        else:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            connection.info['receipt_cleanup_cutoff'] = cutoff.isoformat()
            connection.connection.driver_connection.create_function('xiquan_receipt_cutoff',0,
                lambda:connection.info.get('receipt_cleanup_cutoff',''))
        maintenance = connection.execute(select(BusinessStateModel.maintenance).where(BusinessStateModel.id==1)).scalar_one()
        pending = connection.execute(select(ResetTaskModel.id).where(ResetTaskModel.status.in_(['queued','running'])).limit(1)).first()
        if maintenance or pending:
            connection.rollback(); return result
        for jobs,attempts,label in [(ServicePrintJob.__table__,ServicePrintAttempt.__table__,'order_jobs'),
                                    (PrintJob.__table__,SettlementPrintAttempt.__table__,'settlement_jobs')]:
            ids = connection.execute(select(jobs.c.id).where(jobs.c.created_at<cutoff)
                .order_by(jobs.c.created_at,jobs.c.id).limit(batch_limit)).scalars().all()
            if ids:
                connection.execute(attempts.delete().where(attempts.c.job_id.in_(ids)))
                result[label] = connection.execute(jobs.delete().where(jobs.c.id.in_(ids))).rowcount
        connection.commit()
        return result
    finally:
        connection.rollback()
        connection.info.pop('receipt_cleanup_cutoff',None)
        if postgres and locked:
            connection.exec_driver_sql(f'SELECT pg_advisory_unlock({BARRIER_KEY})'); connection.commit()


def cleanup_expired_receipts(now=None):
    from flask import current_app
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool
    from .extensions import db
    engine = db.engine
    if engine.dialect.name=='postgresql':
        uri = current_app.config.get('MAINTENANCE_DATABASE_URL')
        if not uri: raise ValueError('Receipt cleanup requires the configured maintenance database connection')
        owner = make_url(uri); runtime=engine.url
        if (owner.host,owner.port or 5432,owner.database)!=(runtime.host,runtime.port or 5432,runtime.database):
            raise ValueError('Receipt cleanup database endpoint differs')
        engine = create_engine(uri,poolclass=NullPool,connect_args={'connect_timeout':10})
    totals = {'order_jobs':0,'settlement_jobs':0}
    try:
        # One bounded wake-up; another pass catches up without holding a long lock.
        for _ in range(100):
            with engine.connect() as connection:
                counts = cleanup_expired_receipts_with_owner(connection,now)
            for key in totals: totals[key]+=counts[key]
            if not any(counts.values()): break
        return totals
    finally:
        if engine is not db.engine: engine.dispose()


def start_receipt_cleanup(app):
    """Restart catch-up and midnight work; failure never takes down the API."""
    if app.config.get('TESTING') or app.config.get('MAINTENANCE_PROCESS') or not app.config.get('MAINTENANCE_DATABASE_URL'): return
    from .extensions import socketio
    def worker():
        while True:
            try:
                with app.app_context(): cleanup_expired_receipts()
            except Exception:
                app.logger.error('Receipt cleanup deferred; inspect private maintenance configuration. No business data cleared.')
            # At midnight a busy writer may delay the lock: retry every minute.
            now = datetime.now(timezone.utc)
            socketio.sleep(min(60,max(1,(next_midnight(now)-now).total_seconds())))
    socketio.start_background_task(worker)
