"""Fixed reset connections. The SQL guards are authoritative for all writers."""
from contextlib import contextmanager

from flask import current_app, has_request_context, request
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from .extensions import db

BARRIER_KEY = 713829417
_registered = False


def shared_barrier(connection):
    from .api.errors import ApiError
    from .models import BusinessStateModel
    if connection.info.get('reset_task_id'):
        return  # Only the dedicated worker connection sets this private Python state.
    if not inspect(connection).has_table('business_state'):
        if has_request_context() and request.path.startswith('/api/'):
            raise ApiError('数据库结构尚未升级', 503, 'BUSINESS_MAINTENANCE')
        return  # Structural maintenance of a pre-period schema, never API writes.
    if connection.dialect.name == 'postgresql':
        acquired = connection.exec_driver_sql(
            f'SELECT pg_try_advisory_xact_lock_shared({BARRIER_KEY})').scalar_one()
        if not acquired:
            raise ApiError('正在维护，请稍后重试', 503, 'BUSINESS_MAINTENANCE')
    state = connection.execute(select(BusinessStateModel.maintenance).where(
        BusinessStateModel.id == 1)).scalar_one_or_none()
    if state:
        raise ApiError('正在维护，请稍后重试', 503, 'BUSINESS_MAINTENANCE')


def register_barrier(app):
    global _registered
    with app.app_context():
        if db.engine.dialect.name == 'sqlite':
            @event.listens_for(db.engine, 'connect')
            def sqlite_owner(raw, record):
                raw.create_function('xiquan_reset_owner', 0, lambda: record.info.get('reset_task_id', ''))
    if not _registered:
        @event.listens_for(Session, 'before_flush')
        def flush_barrier(session, _context, _instances):
            shared_barrier(session.connection())

        @event.listens_for(Session, 'do_orm_execute')
        def mutation_barrier(execution):
            if (not execution.is_select or getattr(execution.statement, '_for_update_arg', None) is not None):
                shared_barrier(execution.session.connection())
        _registered = True

    @app.before_request
    def request_barrier():
        if request.path.startswith('/api/') and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            shared_barrier(db.session.connection())


def install_barrier_guards(connection):
    """All runtime writes acquire barrier first; grants also prohibit control DML."""
    control = {'business_state', 'business_periods', 'access_policies', 'reset_tasks', 'reset_events'}
    tables = (set(db.metadata.tables) & set(inspect(connection).get_table_names())) - control
    if connection.dialect.name == 'sqlite':
        for name in tables:
            for operation in ('INSERT', 'UPDATE', 'DELETE'):
                connection.exec_driver_sql(f'''CREATE TRIGGER IF NOT EXISTS barrier_{name}_{operation.lower()}
                    BEFORE {operation} ON {name}
                    WHEN EXISTS (SELECT 1 FROM business_state WHERE id=1 AND maintenance=1
                        AND (maintenance_reset_id IS NULL OR maintenance_reset_id != xiquan_reset_owner()))
                    BEGIN SELECT RAISE(ABORT, 'BUSINESS_MAINTENANCE'); END''')
        return
    if connection.dialect.name != 'postgresql':
        return
    # Only the actual login AND a granted session-level exclusive barrier can
    # perform reset writes. SET ROLE/GUC/shared-lock possession grants nothing.
    reset_owner = f"""session_user = 'xiquan_reset' AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_locks WHERE locktype='advisory'
        AND pid=pg_catalog.pg_backend_pid() AND classid=0 AND objid={BARRIER_KEY}
        AND objsubid=1 AND mode='ExclusiveLock' AND granted)"""
    maintenance_owner = f"""EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_roles r ON r.oid=c.relowner
        WHERE c.oid=TG_RELID AND r.rolname=session_user)
        AND EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
          JOIN pg_catalog.pg_roles r ON r.oid=n.nspowner
          JOIN pg_catalog.pg_database d ON d.datname=current_database()
          JOIN pg_catalog.pg_roles login ON login.rolname=session_user
          WHERE n.nspname='public' AND login.oid=CASE
            WHEN r.rolname='pg_database_owner' THEN d.datdba ELSE n.nspowner END)
        AND EXISTS (SELECT 1 FROM pg_catalog.pg_locks WHERE locktype='advisory'
          AND pid=pg_catalog.pg_backend_pid() AND classid=0 AND objid={BARRIER_KEY}
          AND objsubid=1 AND mode='ExclusiveLock' AND granted)"""
    connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION public.xiquan_write_barrier()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
          IF NOT (({reset_owner}) OR ({maintenance_owner})) THEN
            IF NOT pg_catalog.pg_try_advisory_xact_lock_shared({BARRIER_KEY}) THEN
              RAISE EXCEPTION 'BUSINESS_MAINTENANCE';
            END IF;
            IF EXISTS (SELECT 1 FROM public.business_state WHERE id=1 AND maintenance) THEN
              RAISE EXCEPTION 'BUSINESS_MAINTENANCE';
            END IF;
          END IF;
          RETURN NULL;
        END; $$''')
    connection.exec_driver_sql('REVOKE ALL ON FUNCTION public.xiquan_write_barrier() FROM PUBLIC')
    for name in tables:
        connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS a_business_barrier ON public.{name}')
        connection.exec_driver_sql(f'''CREATE TRIGGER a_business_barrier
            BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{name}
            FOR EACH STATEMENT EXECUTE FUNCTION public.xiquan_write_barrier()''')
    connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION public.xiquan_control_guard()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
            JOIN pg_catalog.pg_roles r ON r.oid=n.nspowner
            JOIN pg_catalog.pg_database d ON d.datname=current_database()
            JOIN pg_catalog.pg_roles login ON login.rolname=session_user
            WHERE n.nspname='public' AND login.oid=CASE
              WHEN r.rolname='pg_database_owner' THEN d.datdba ELSE n.nspowner END) THEN
            RETURN COALESCE(NEW, OLD);
          END IF;
          IF TG_TABLE_NAME='business_state' AND TG_OP='UPDATE' THEN
            IF pg_catalog.pg_trigger_depth()>1 AND NEW.business_revision=OLD.business_revision+1
               AND (to_jsonb(NEW)-'business_revision')=(to_jsonb(OLD)-'business_revision') THEN
              RETURN NEW;
            END IF;
          END IF;
          IF session_user='xiquan_reset' AND TG_TABLE_NAME='reset_tasks' THEN
            RETURN COALESCE(NEW, OLD);
          END IF;
          IF TG_TABLE_NAME <> 'access_policies' AND ({reset_owner}) THEN RETURN COALESCE(NEW, OLD); END IF;
          RAISE EXCEPTION 'reset control access denied';
        END; $$''')
    connection.exec_driver_sql('REVOKE ALL ON FUNCTION public.xiquan_control_guard() FROM PUBLIC')
    for name in control:
        connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS reset_control ON public.{name}')
        connection.exec_driver_sql(f'''CREATE TRIGGER reset_control BEFORE INSERT OR UPDATE OR DELETE
            ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.xiquan_control_guard()''')
        connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS reset_no_truncate ON public.{name}')
        connection.exec_driver_sql(f'''CREATE TRIGGER reset_no_truncate BEFORE TRUNCATE ON public.{name}
            FOR EACH STATEMENT EXECUTE FUNCTION public.xiquan_append_only()''')
    connection.exec_driver_sql('''CREATE OR REPLACE FUNCTION public.xiquan_business_revision()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN UPDATE public.business_state SET business_revision=business_revision+1 WHERE id=1;
        RETURN NULL; END; $$''')
    connection.exec_driver_sql('REVOKE ALL ON FUNCTION public.xiquan_business_revision() FROM PUBLIC')


@contextmanager
def control_connection():
    uri = current_app.config.get('RESET_DATABASE_URL')
    if db.engine.dialect.name == 'postgresql':
        if not uri:
            raise RuntimeError('RESET_DATABASE_URL is required')
        reset_url = make_url(uri)
        runtime_url = db.engine.url
        if (reset_url.host, reset_url.port or 5432, reset_url.database) != (
                runtime_url.host, runtime_url.port or 5432, runtime_url.database):
            raise RuntimeError('Reset connection must target the configured runtime database endpoint')
        engine = create_engine(uri, poolclass=NullPool)
    else:
        engine = db.engine
    try:
        with engine.connect() as connection:
            if connection.dialect.name == 'postgresql':
                row = connection.exec_driver_sql("SELECT session_user, current_database(), "
                    "(SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls "
                    "FROM pg_roles WHERE rolname=session_user), "
                    "(SELECT pg_has_role(session_user,nspowner,'MEMBER') "
                    "FROM pg_namespace WHERE nspname='public'), "
                    "EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' "
                    "AND pg_has_role(session_user,tableowner,'MEMBER'))").one()
                if row[0] != 'xiquan_reset' or row[2] or row[3] or row[4]:
                    raise RuntimeError('Reset requires the minimal xiquan_reset login role')
                if row[1] != db.engine.url.database:
                    raise RuntimeError('Reset database differs from runtime database')
                connection.rollback()
            yield connection
    finally:
        if engine is not db.engine:
            engine.dispose()


@contextmanager
def exclusive_barrier(connection, task_id, wait=False):
    """One physical connection, explicit unlock, never reconnect after disconnect."""
    file_lock = None
    locked = False
    try:
        if connection.in_transaction():
            connection.rollback()
        if connection.dialect.name == 'postgresql':
            if wait:
                connection.exec_driver_sql(f'SELECT pg_advisory_lock({BARRIER_KEY})')
                locked = True
            else:
                locked = connection.exec_driver_sql(
                    f'SELECT pg_try_advisory_lock({BARRIER_KEY})').scalar_one()
            connection.commit()
        else:
            # SQLite has no session locks across commit/backup phases. Lock a
            # sibling of the DB (same path for every process), then use IMMEDIATE
            # transactions and a durable owner to exclude ordinary DB writers.
            path = connection.engine.url.database
            if not path or path == ':memory:':
                raise RuntimeError('Reset requires a file SQLite database')
            file_lock = open(path + '.reset-lock', 'a+b')
            file_lock.seek(0)
            try:
                if __import__('os').name == 'nt':
                    import msvcrt
                    msvcrt.locking(file_lock.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file_lock.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
                locked = True
            except OSError:
                locked = False
        if not locked:
            from .api.errors import ApiError
            raise ApiError('正在维护，请稍后重试', 503, 'BUSINESS_MAINTENANCE')
        connection.info['reset_task_id'] = task_id
        yield connection
    finally:
        try:
            if not connection.invalidated:
                connection.rollback()
                connection.info.pop('reset_task_id', None)
                if locked and connection.dialect.name == 'postgresql':
                    connection.exec_driver_sql(f'SELECT pg_advisory_unlock({BARRIER_KEY})')
                    connection.commit()
        except Exception:
            connection.invalidate()
            raise
        finally:
            if file_lock:
                file_lock.close()
