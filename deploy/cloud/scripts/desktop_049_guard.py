"""Additive registration migration and isolated PG17 security rehearsal."""
import argparse
import importlib
import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from app import create_app
from app.extensions import db
from app.business_barrier import exclusive_barrier
from app.operations_upgrade import maintenance_connection
from app.operations_backup import _verify_snapshot_audit
from stock_guard import roles, state, revision, GuardError, require

OLD = '20261007_ordering_cost'
HEAD = '20261008_registration_token'
NEW = {'registration_token_state', 'registration_rate_limits', 'registration_receipts', 'registration_token_views'}


def require_isolated(url):
    require(bool(url.host) and url.host.startswith('xiquan-operations-restore-') and
            url.database == 'operations_restore', 'Security fixture writes require isolated restore')


def snapshot(connection):
    require(connection.exec_driver_sql('SHOW server_version_num').scalar_one().startswith('17'), 'PG17 required')
    connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
    version = revision(connection)
    require(version in (OLD, HEAD), 'Unexpected schema revision')
    tables = {}
    inspector = inspect(connection)
    for table in sorted(inspector.get_table_names()):
        require(table.replace('_', '').isalnum(), 'Unexpected table identifier')
        columns = {row['name']: {'type': str(row['type']), 'nullable': row['nullable'],
                                'default': row['default']} for row in inspector.get_columns(table)}
        projection = "to_jsonb(t) - 'version_num'" if table == 'alembic_version' else 'to_jsonb(t)'
        count, digest = connection.exec_driver_sql(f'''SELECT count(*), encode(sha256(convert_to(
            COALESCE(string_agg(({projection})::text,E'\\n' ORDER BY ({projection})::text COLLATE "C"),''),
            'UTF8')),'hex') FROM public."{table}" t''').one()
        tables[table] = dict(columns=columns, rows=count, sha256=digest)
    role_hash = connection.exec_driver_sql("""SELECT encode(sha256(convert_to(string_agg(
        row_to_json(r)::text,E'\n' ORDER BY rolname),'UTF8')),'hex') FROM pg_authid r
        WHERE rolname IN ('xiquan_app','xiquan_reset','xiquan_backup')""").scalar_one()
    owners = dict(connection.exec_driver_sql("""SELECT c.relname,pg_get_userbyid(c.relowner)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p')""").all())
    grants = {name: list(acl or []) for name, acl in connection.exec_driver_sql("""SELECT c.relname,
        ARRAY(SELECT a::text FROM unnest(COALESCE(c.relacl,acldefault('r',c.relowner))) a ORDER BY a::text)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p')""")}
    require(_verify_snapshot_audit(connection), 'Audit evidence invalid')
    return dict(tables=tables, roles=role_hash, owners=owners, grants=grants, schema=version, audit_valid=True)


def compare(before, after):
    require(before['schema'] == OLD and after['schema'] == HEAD, 'Unexpected schema upgrade')
    require(not (set(before['tables']) & NEW) and set(after['tables']) == set(before['tables']) | NEW,
            'Unexpected table addition/removal or partial schema')
    require(before['roles'] == after['roles'], 'Database role authority changed')
    require(before['audit_valid'] and after['audit_valid'], 'Audit evidence invalid')
    for name in before['tables']:
        require(before['tables'][name] == after['tables'][name], 'Retained row/column changed: ' + name)
        require(before['owners'][name] == after['owners'][name] and before['grants'][name] == after['grants'][name],
                'Retained ownership/grants changed: ' + name)
    require(all(after['tables'][name]['rows'] == 0 for name in NEW), 'Registration migration must not create fixture rows')


def migrate(connection):
    # Execute ONLY this reviewed additive revision on the already-owned connection.
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration = importlib.import_module('migrations.versions.' + HEAD)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    connection.execute(text('UPDATE alembic_version SET version_num=:head'), {'head': HEAD})


def exercise(app, connection, job):
    """Real competing PG connections. This entry cannot run on a production URL."""
    require_isolated(db.engine.url)
    urls = roles()
    for url in urls.values():
        require_isolated(url)
    # Remove only this clone's owned maintenance before probing trigger semantics;
    # a maintenance denial must never be mistaken for an immutable-table denial.
    with exclusive_barrier(connection, job):
        require(state(connection)['maintenance_reset_id'] == job, 'Clone ownership changed')
        connection.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
        connection.commit()
    runtime = create_engine(urls['runtime'], hide_parameters=True)
    # Runtime privileges AND owner triggers are exercised independently, including empty-table TRUNCATE.
    for engine, runtime_role in ((runtime, True), (db.engine, False)):
        for table in ('registration_receipts', 'registration_token_views'):
            for sql in (f'UPDATE {table} SET key=key', f'DELETE FROM {table}', f'TRUNCATE {table}'):
                with engine.connect() as check:
                    try:
                        check.exec_driver_sql(sql)
                    except Exception as error:
                        code = getattr(getattr(error, 'orig', None), 'sqlstate', None)
                        require(code == '42501' if runtime_role else code == 'P0001', 'Immutable denial category differs')
                        check.rollback()
                    else:
                        check.rollback()
                        raise GuardError('Immutable security evidence mutation allowed')
    with runtime.connect() as check:
        for table in sorted(NEW):
            for operation in ('DELETE', 'TRUNCATE'):
                try:
                    check.exec_driver_sql(f'{operation} FROM {table}' if operation == 'DELETE' else f'TRUNCATE {table}')
                except Exception as error:
                    require(getattr(getattr(error, 'orig', None), 'sqlstate', None) == '42501', 'Runtime destructive grant allowed')
                    check.rollback()
                else:
                    check.rollback()
                    raise GuardError('Runtime destructive write allowed')
    from app.config import Config
    class RuntimeConfig(Config):
        SQLALCHEMY_DATABASE_URI = urls['runtime'].render_as_string(hide_password=False)
        MAINTENANCE_PROCESS = True
        AUTO_CREATE_DB = False
        REGISTRATION_TOKEN_SECRET = secrets.token_urlsafe(48)
    runtime_app = create_app(RuntimeConfig)
    from app.registration_service import register_employee, derive_code
    from app.api.errors import ApiError
    # Fixture terminal is added only to the isolated database, never a real account/policy.
    from app.models import Terminal
    terminal_code = 'registration-proof-' + uuid.uuid4().hex
    with app.app_context():
        db.session.add(Terminal(code=terminal_code, name='Isolated registration rehearsal', is_active=True))
        db.session.commit()
    secret_bytes = RuntimeConfig.REGISTRATION_TOKEN_SECRET.encode()

    def seed_state(expiry):
        seed = secrets.token_hex(32)
        with runtime.begin() as check:
            check.execute(text('''INSERT INTO registration_token_state(id,generation,seed,expires_at,wrong_attempts)
                VALUES(1,1,:seed,:expiry,0) ON CONFLICT(id) DO UPDATE SET generation=registration_token_state.generation+1,
                seed=:seed,expires_at=:expiry,wrong_attempts=0 RETURNING generation'''), dict(seed=seed, expiry=expiry))
            generation = check.exec_driver_sql('SELECT generation FROM registration_token_state WHERE id=1').scalar_one()
        return derive_code(secret_bytes, generation, seed)

    def body(code):
        return dict(username='199' + str(secrets.randbelow(100000000)).zfill(8), display_name='Isolated proof',
                    password=secrets.token_urlsafe(16), role='floor_attendant', code=code,
                    terminal_code=terminal_code, client_channel='desktop')

    code = seed_state(datetime.now(timezone.utc) + timedelta(seconds=180))
    start = threading.Barrier(2)
    outcomes = []
    def contender(payload):
        with runtime_app.app_context():
            start.wait(timeout=10)
            try:
                register_employee(payload, uuid.uuid4().hex, 'isolated-proof')
                outcomes.append('created')
            except ApiError as error:
                outcomes.append(error.code)
            except Exception:
                outcomes.append('unexpected')
            finally:
                db.session.remove()
    threads = [threading.Thread(target=contender, args=(body(code),), daemon=True) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(20)
    require(all(not thread.is_alive() for thread in threads) and sorted(outcomes) == ['REGISTRATION_CODE_INVALID', 'created'],
            'Concurrent authorization was not transactionally one-use')
    # Hold the singleton until its original deadline has passed. Confirm the competing backend actually waits.
    deadline = datetime.now(timezone.utc) + timedelta(seconds=2)
    code = seed_state(deadline)
    outcomes.clear()
    waiting = threading.Event()
    pid = []
    def expiring_contender():
        with runtime_app.app_context():
            pid.append(db.session.execute(text('SELECT pg_backend_pid()')).scalar_one())
            waiting.set()
            try:
                register_employee(body(code), uuid.uuid4().hex, 'isolated-expiry')
                outcomes.append('created')
            except ApiError as error:
                outcomes.append(error.code)
            except Exception:
                outcomes.append('unexpected')
            finally:
                db.session.remove()
    with runtime.connect() as holder:
        holder.exec_driver_sql('SELECT id FROM registration_token_state WHERE id=1 FOR UPDATE')
        thread = threading.Thread(target=expiring_contender, daemon=True)
        thread.start()
        require(waiting.wait(10), 'Expiry contender did not start')
        limit = time.monotonic() + 10
        locked = False
        while time.monotonic() < limit:
            with db.engine.connect() as observer:
                locked = observer.execute(text("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"), {'pid': pid[0]}).scalar()
            if locked: break
            time.sleep(0.05)
        require(locked, 'Expiry contention did not acquire a real PostgreSQL lock wait')
        time.sleep(max(0, (deadline - datetime.now(timezone.utc)).total_seconds()) + 0.2)
        holder.commit()
    thread.join(20)
    require(not thread.is_alive() and outcomes == ['REGISTRATION_CODE_INVALID'], 'Authorization expired during lock wait was accepted')
    runtime.dispose()
    return dict(pg17=True, one_use=True, expiry_after_lock=True, immutable=True, runtime_grants=True, isolated=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['inspect', 'claim', 'migrate', 'release', 'proof'])
    parser.add_argument('--job', required=True)
    parser.add_argument('--baseline')
    args = parser.parse_args()
    require(str(uuid.UUID(args.job)) == args.job, 'Invalid maintenance identity')
    app = create_app()
    with app.app_context(), maintenance_connection() as connection:
        isolated = bool(db.engine.url.host) and db.engine.url.host.startswith('xiquan-operations-restore-')
        if not isolated: roles()
        if args.mode == 'proof':
            result = exercise(app, connection, args.job)
        elif args.mode == 'inspect':
            result = snapshot(connection)
        else:
            with exclusive_barrier(connection, args.job):
                current = state(connection)
                require(not connection.exec_driver_sql("SELECT count(*) FROM reset_tasks WHERE status IN ('queued','running')").scalar_one(), 'Unfinished reset')
                if args.mode == 'claim':
                    require(revision(connection) == OLD and not current['maintenance'] and not current['maintenance_reset_id'], 'Expected predecessor and no maintenance')
                    connection.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'), {'job': args.job})
                    connection.commit()
                    result = snapshot(connection)
                else:
                    require(current['maintenance'] and current['maintenance_reset_id'] == args.job, 'Maintenance belongs to another job')
                    before = snapshot(connection)
                    require(args.baseline and before == json.loads(Path(args.baseline).read_text()), 'Checkpoint data changed')
                    if args.mode == 'migrate':
                        require(revision(connection) == OLD, 'Exact predecessor required')
                        migrate(connection)
                        result = snapshot(connection)
                        compare(before, result)
                        connection.commit()
                    else:
                        require(revision(connection) == HEAD, 'Expected registration schema')
                        connection.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
                        connection.commit()
                        result = dict(released=True, schema=HEAD)
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, GuardError) else type(error).__name__ + ': inspect private evidence'
        print('DESKTOP_GUARD_STOPPED: ' + message, file=__import__('sys').stderr)
        raise SystemExit(1)
