"""One-shot additive 0.4.5 migration; never removes any business/history rows."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from sqlalchemy import inspect, text
from app import create_app
from app.extensions import db
from app.business_barrier import exclusive_barrier
from app.operations_upgrade import maintenance_connection
from app.operations_backup import _verify_snapshot_audit
from stock_guard import roles, state, revision, GuardError, require

OLD = '20261005_independent_stock'
HEAD = '20261007_desktop_ops'


def snapshot(connection):
    require(connection.exec_driver_sql('SHOW server_version_num').scalar_one().startswith('17'), 'PG17 required')
    connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
    version = revision(connection)
    require(version in (OLD, HEAD), 'Unexpected schema revision')
    tables = {}
    for table in sorted(inspect(connection).get_table_names()):
        require(table.replace('_', '').isalnum(), 'Unexpected table identifier')
        columns = {row['name']: str(row['type']) for row in inspect(connection).get_columns(table)}
        projection = 'to_jsonb(t)'
        if table in ('members', 'catalog_items') and version == HEAD:
            require('deleted_at' in columns, 'Missing reviewed tombstone column')
            require(not connection.exec_driver_sql(f'SELECT count(*) FROM "{table}" WHERE deleted_at IS NOT NULL').scalar_one(),
                    'New archive column unexpectedly populated during migration')
            columns.pop('deleted_at')
            projection += " - 'deleted_at'"
        count, digest = connection.exec_driver_sql(f'''SELECT count(*), encode(sha256(convert_to(
            COALESCE(string_agg(({projection})::text,E'\\n' ORDER BY ({projection})::text COLLATE "C"),''),
            'UTF8')),'hex') FROM public."{table}" t''').one()
        tables[table] = {'columns': columns, 'rows': count, 'sha256': digest}
    role_hash = connection.exec_driver_sql("""SELECT encode(sha256(convert_to(string_agg(
        row_to_json(r)::text,E'\n' ORDER BY rolname),'UTF8')),'hex') FROM pg_authid r
        WHERE rolname IN ('xiquan_app','xiquan_reset','xiquan_backup')""").scalar_one()
    owners = dict(connection.exec_driver_sql("""SELECT c.relname, pg_get_userbyid(c.relowner)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p')""").all())
    require(_verify_snapshot_audit(connection), 'Audit evidence invalid')
    return {'tables': tables, 'roles': role_hash, 'owners': owners, 'audit_valid': True}


def compare(before, after):
    require(set(before['tables']) == set(after['tables']), 'Unexpected table addition/removal')
    require(before['roles'] == after['roles'] and before['owners'] == after['owners'], 'Database authority changed')
    for table in before['tables']:
        if table != 'alembic_version':
            require(before['tables'][table] == after['tables'][table], 'Retained row/column changed: ' + table)
    require(before['audit_valid'] and after['audit_valid'], 'Audit evidence invalid')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['inspect', 'claim', 'migrate', 'release'])
    parser.add_argument('--job', required=True)
    parser.add_argument('--baseline')
    args = parser.parse_args()
    require(len(args.job) == 36, 'Invalid maintenance identity')
    app = create_app()
    with app.app_context(), maintenance_connection() as connection:
        isolated = db.engine.url.host.startswith('xiquan-operations-restore-') and db.engine.url.database == 'operations_restore'
        if not isolated:
            roles()
        if args.mode == 'inspect':
            result = snapshot(connection)
        else:
            with exclusive_barrier(connection, args.job):
                current = state(connection)
                require(not connection.exec_driver_sql("SELECT count(*) FROM reset_tasks WHERE status IN ('queued','running')").scalar_one(),
                        'Unfinished reset must be resolved first')
                if args.mode == 'claim':
                    require(revision(connection) == OLD and not current['maintenance'] and not current['maintenance_reset_id'],
                            'Expected direct predecessor and no existing maintenance')
                    connection.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'), {'job':args.job})
                    connection.commit()
                    result = snapshot(connection)
                else:
                    require(current['maintenance'] and current['maintenance_reset_id'] == args.job, 'Maintenance belongs to another job')
                    before = snapshot(connection)
                    require(args.baseline and before == json.loads(Path(args.baseline).read_text()), 'Checkpoint data changed')
                    if args.mode == 'migrate':
                        require(revision(connection) == OLD, 'DDL never automatically repeated')
                        from alembic.migration import MigrationContext
                        from alembic.operations import Operations
                        file = Path('/app/migrations/versions/' + HEAD + '.py')
                        spec = importlib.util.spec_from_file_location('reviewed_desktop_migration', file)
                        migration = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(migration)
                        require(migration.revision == HEAD and migration.down_revision == OLD, 'Migration identity mismatch')
                        with Operations.context(MigrationContext.configure(connection)):
                            migration.upgrade()
                        connection.execute(text('UPDATE alembic_version SET version_num=:head WHERE version_num=:old'), {'head':HEAD,'old':OLD})
                        result = snapshot(connection)
                        compare(before, result)
                        connection.commit()
                    else:
                        require(revision(connection) == HEAD, 'Expected upgraded schema')
                        connection.execute(text('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1'))
                        connection.commit()
                        result = {'released': True, 'schema': HEAD}
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, GuardError) else 'Migration guard failed; inspect private evidence'
        print('DESKTOP_GUARD_STOPPED: ' + message, file=__import__('sys').stderr)
        raise SystemExit(1)
