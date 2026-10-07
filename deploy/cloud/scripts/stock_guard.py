"""Run only inside the verified image, via stock_deploy.py's private mount."""
import argparse
import hashlib
import json
import os
import threading
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from app import create_app
from app.extensions import db
from app.business_barrier import exclusive_barrier
from app.operations_upgrade import maintenance_connection
from app.operations_backup import _verify_snapshot_audit

OLD = '20261004_catalog_packages'
HEAD = '20261005_independent_stock'
NEW = {'stock_items', 'stock_movements', 'order_stock_consumptions'}


class GuardError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise GuardError(message)


def state(c):
    return dict(c.exec_driver_sql('SELECT * FROM business_state WHERE id=1').mappings().one())


def revision(c):
    return c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()


def roles():
    from app.deployment_checks import check_database_roles
    urls = {k: make_url(os.environ[n]) for k, n in (
        ('runtime', 'RUNTIME_DATABASE_URL'), ('reset', 'RESET_DATABASE_URL'),
        ('backup', 'RESET_BACKUP_DATABASE_URL'))}
    check_database_roles(urls)
    return urls


def snapshot(c):
    require(c.exec_driver_sql("SHOW server_version_num").scalar_one().startswith('17'), 'PG17 required')
    c.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
    tables = {}
    for table in sorted(inspect(c).get_table_names()):
        require(table.replace('_', '').isalnum(), 'Unexpected identifier')
        cols = {v['name']: str(v['type']) for v in inspect(c).get_columns(table)}
        projection = 'to_jsonb(t)'
        if table == 'order_items' and revision(c) == HEAD:
            require('inventory_mode' in cols, 'Missing reviewed addition')
            projection += " - 'inventory_mode'"
            cols.pop('inventory_mode')
        digest = c.exec_driver_sql(f'''SELECT count(*), encode(sha256(convert_to(
            COALESCE(string_agg(({projection})::text,E'\\n' ORDER BY ({projection})::text COLLATE "C"),''),
            'UTF8')),'hex') FROM public."{table}" t''').one()
        tables[table] = {'columns': cols, 'rows': digest[0], 'sha256': digest[1]}
    # Hash role credentials rather than emitting them; no ALTER ROLE on production.
    role_hash = c.exec_driver_sql("""SELECT encode(sha256(convert_to(string_agg(
        row_to_json(r)::text,E'\n' ORDER BY rolname),'UTF8')),'hex') FROM pg_authid r
        WHERE rolname IN ('xiquan_app','xiquan_reset','xiquan_backup')""").scalar_one()
    owners = dict(c.exec_driver_sql("""SELECT c.relname, pg_get_userbyid(c.relowner)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p')""").all())
    require(_verify_snapshot_audit(c), 'Audit chain invalid')
    return dict(tables=tables, roles=role_hash, owners=owners, audit_valid=True)


def compare(before, after):
    require(set(after['tables']) == set(before['tables']) | NEW, 'Unexpected table additions/removals')
    require(not (set(before['tables']) & NEW), 'Partial stock schema')
    for table in before['tables']:
        if table != 'alembic_version':
            require(before['tables'][table] == after['tables'][table], 'An original column/row changed: ' + table)
        require(before['owners'][table] == after['owners'][table], 'Original ownership changed')
    require(before['roles'] == after['roles'], 'Role LOGIN/password/authority changed')
    require(after['tables']['stock_movements']['rows'] == 0 and
            after['tables']['order_stock_consumptions']['rows'] == 0, 'Unexpected new history')


def exercise(app, c, job):
    """Actual dedicated restored PG17 sessions; never accepts a production URL."""
    url = db.engine.url
    require(url.host.startswith('xiquan-operations-restore-') and url.database == 'operations_restore',
            'Fixture writes require isolated restore')
    urls = roles()
    runtime = create_engine(urls['runtime'], hide_parameters=True)
    # Actual statements, including TRUNCATE, must be denied even on empty tables.
    for name in ('stock_movements', 'order_stock_consumptions', 'audit_logs'):
        for operation in (f'UPDATE {name} SET id=id', f'DELETE FROM {name}', f'TRUNCATE {name}'):
            with runtime.connect() as rc:
                try:
                    rc.exec_driver_sql(operation)
                except Exception as error:
                    require(getattr(getattr(error, 'orig', None), 'sqlstate', None) == '42501', 'Expected privilege denial')
                    rc.rollback()
                else:
                    rc.rollback()
                    raise RuntimeError('Immutable table write allowed')
    with runtime.connect() as rc:
        try:
            rc.exec_driver_sql('CREATE TABLE public.stock_forbidden_probe(id integer)')
        except Exception as error:
            require(getattr(getattr(error, 'orig', None), 'sqlstate', None) == '42501', 'DDL denial required')
            rc.rollback()
        else:
            rc.rollback()
            raise RuntimeError('Runtime DDL allowed')
    runtime.dispose()
    with exclusive_barrier(c, job):
        require(state(c)['maintenance_reset_id'] == job, 'Clone ownership changed')
        c.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
        c.commit()
    # A separate Flask app binds its thread-local sessions to the actual runtime login.
    from app.config import Config
    class RuntimeConfig(Config):
        SQLALCHEMY_DATABASE_URI = urls['runtime'].render_as_string(hide_password=False)
        MAINTENANCE_PROCESS = True
        AUTO_CREATE_DB = False
    runtime_app = create_app(RuntimeConfig)
    from app.models import StockItem, Employee, IdempotencyRecord, StockMovement
    from app.stock_service import change_balance
    from app.financial_lock import serialize_financial_session
    from app.idempotency_service import idempotency_store
    with runtime_app.app_context():
        employee_id = Employee.query.filter_by(is_active=True).first().id
        master = StockItem(name='isolated-stock-proof-' + job, base_unit='袋', stock_quantity=Decimal('1'))
        db.session.add(master)
        db.session.commit()
        stock_id = master.id
    barrier = threading.Barrier(2)
    results, failures, pids = [], [], []
    def consume(key, concurrent=False):
        with runtime_app.test_request_context('/stock-proof', json={'quantity': '1'}):
            if concurrent:
                # Bind distinct connections before racing through the real serialization primitive.
                pid = db.session.connection().exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
                pids.append(pid)
                barrier.wait(timeout=20)
            serialize_financial_session(db.session)
            previous = db.session.get(IdempotencyRecord, key)
            if previous:
                db.session.rollback()
                return 'replay'
            row = StockItem.query.filter_by(id=stock_id).with_for_update().one()
            if row.stock_quantity < 1:
                db.session.rollback()
                return 'insufficient'
            employee = db.session.get(Employee, employee_id)
            movement = change_balance(row, Decimal('-1'), employee, 'loss', 'isolated PG17 proof')
            idempotency_store(key, 'stock-proof', 200, {'movement': movement.id})
            db.session.commit()
            return 'applied'
    def worker(key):
        try:
            results.append((key, consume(key, True)))
        except Exception:
            failures.append(True)
    keys = [hashlib.sha256((job + str(i)).encode()).hexdigest() for i in range(2)]
    threads = [threading.Thread(target=worker, args=(key,), daemon=True) for key in keys]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=40)
    require(not failures and all(not t.is_alive() for t in threads) and len(set(pids)) == 2,
            'Two actual sessions did not complete')
    require(sorted(result for _, result in results) == ['applied', 'insufficient'], 'Oversell gate failed')
    winner = next(key for key, result in results if result == 'applied')
    require(consume(winner) == 'replay', 'Retry gate failed')
    with runtime_app.app_context():
        require(db.session.get(StockItem, stock_id).stock_quantity == 0 and
                StockMovement.query.filter_by(stock_item_id=stock_id).count() == 1, 'Retry changed stock')
    c.rollback()
    require(_verify_snapshot_audit(c), 'Fixture audit invalid')
    return dict(actual_pg17=True, distinct_sessions=2, oversell_denied=True, retry_single_movement=True,
                immutable_role_writes_denied=True, runtime_ddl_denied=True, fixture_scope='isolated-only')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['claim', 'inspect', 'migrate', 'release', 'proof'])
    parser.add_argument('--job', required=True)
    parser.add_argument('--baseline')
    args = parser.parse_args()
    require(len(args.job) == 36, 'Invalid maintenance identity')
    app = create_app()
    with app.app_context(), maintenance_connection() as c:
        isolated_migration = (args.mode == 'migrate' and db.engine.url.host.startswith('xiquan-operations-restore-')
                              and db.engine.url.database == 'operations_restore')
        if not isolated_migration:
            roles()
        if args.mode == 'inspect':
            result = snapshot(c)
        elif args.mode == 'proof':
            result = exercise(app, c, args.job)
        else:
            with exclusive_barrier(c, args.job):
                current = state(c)
                require(not c.exec_driver_sql("SELECT count(*) FROM reset_tasks WHERE status IN ('queued','running')").scalar_one(), 'Pending reset')
                if args.mode == 'claim':
                    require(revision(c) == OLD and not current['maintenance'] and not current['maintenance_reset_id'],
                            'Fresh direct predecessor and no existing maintenance required')
                    c.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'), {'job': args.job})
                    c.commit()
                    result = snapshot(c)
                else:
                    require(current['maintenance'] and current['maintenance_reset_id'] == args.job, 'Maintenance is not owned by this job')
                    if args.mode == 'migrate':
                        require(revision(c) == OLD, 'Unknown/partial migration; no automatic retry')
                        before = snapshot(c)
                        if args.baseline:
                            require(before == json.loads(Path(args.baseline).read_text()), 'Original state changed')
                        from alembic.migration import MigrationContext
                        from alembic.operations import Operations
                        import importlib.util
                        path = Path('/app/migrations/versions/20261005_independent_stock.py')
                        spec = importlib.util.spec_from_file_location('reviewed_stock_migration', path)
                        migration = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(migration)
                        require(migration.revision == HEAD and migration.down_revision == OLD, 'Migration range changed')
                        with Operations.context(MigrationContext.configure(c)):
                            migration.upgrade()
                        c.execute(text('UPDATE alembic_version SET version_num=:head WHERE version_num=:old'), {'head': HEAD, 'old': OLD})
                        for table in NEW:
                            require({v['name'] for v in inspect(c).get_columns(table)} == set(db.metadata.tables[table].columns.keys()),
                                    'Unexpected new table columns')
                        require(c.exec_driver_sql("""SELECT count(*) FROM catalog_items c FULL OUTER JOIN stock_items s
                            ON s.legacy_catalog_item_id=c.id WHERE
                            (c.kind='product' AND c.stock_tracked AND
                             (s.id IS NULL OR s.name<>c.name OR s.category<>c.category OR s.base_unit<>'原销售单位'
                              OR s.stock_quantity<>c.stock_quantity OR s.low_stock_threshold<>c.low_stock_threshold
                              OR s.is_active<>c.is_active OR s.units_per_package<>1 OR s.package_unit<>'' OR s.package_spec<>''))
                            OR (s.id IS NOT NULL AND (c.id IS NULL OR c.kind<>'product' OR NOT c.stock_tracked))""").scalar_one() == 0,
                                'Legacy stock mapping differs')
                        require(c.exec_driver_sql("SELECT count(*) FROM order_items WHERE inventory_mode<>'legacy'").scalar_one() == 0,
                                'Historical order mode changed')
                        after = snapshot(c)
                        compare(before, after)
                        c.commit()
                        result = after
                    else:
                        require(revision(c) == HEAD, 'Wrong release head')
                        result = snapshot(c)
                        require(args.baseline and result == json.loads(Path(args.baseline).read_text()), 'Postmigration state changed')
                        c.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
                        c.commit()
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Driver retains the checkpoint; never leak DB parameters or customer rows.
        message = str(error) if isinstance(error, GuardError) else 'private schema, preservation, ownership or role gate failed'
        print('STOCK_GUARD_STOPPED: ' + message, file=__import__('sys').stderr)
        raise SystemExit(1)
