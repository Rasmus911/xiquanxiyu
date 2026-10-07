"""Additive 0.4.8 guard: empty master costs and exact product/service fixes only."""
import argparse
import json
from pathlib import Path

from sqlalchemy import inspect, text
from app import create_app
from app.extensions import db
from app.business_barrier import exclusive_barrier
from app.operations_upgrade import maintenance_connection
from app.operations_backup import _verify_snapshot_audit
from stock_guard import roles, state, revision, GuardError, require

OLD = '20261007_insights_cost'
HEAD = '20261007_ordering_cost'
CATALOG_SELECTOR = "name IN ('澡巾','备品','搓泥宝') OR reference_code IN ('bath.towel','bath.supplies','bath.mud')"


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
        projection = 'to_jsonb(t)'
        if table == 'stock_items':
            projection += " - 'unit_cost'"
        elif table == 'catalog_items':
            projection = f"CASE WHEN {CATALOG_SELECTOR} THEN to_jsonb(t) - 'kind' - 'stock_tracked' ELSE to_jsonb(t) END"
        elif table == 'business_state':
            projection += " - 'business_revision'"
        elif table == 'alembic_version':
            projection += " - 'version_num'"
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
    flags = {row['id']: {'kind': row['kind'], 'stock_tracked': row['stock_tracked']} for row in
             connection.exec_driver_sql('SELECT id,kind,stock_tracked FROM catalog_items WHERE ' + CATALOG_SELECTOR).mappings()}
    cost_nonnull = connection.exec_driver_sql('SELECT count(*) FROM stock_items WHERE unit_cost IS NOT NULL').scalar_one() if 'unit_cost' in tables['stock_items']['columns'] else None
    business_revision = connection.exec_driver_sql('SELECT business_revision FROM business_state WHERE id=1').scalar_one()
    return {'tables': tables, 'roles': role_hash, 'owners': owners, 'audit_valid': True,
            'catalog_flags': flags, 'unit_cost_nonnull': cost_nonnull,
            'business_revision': business_revision, 'schema': version}


def compare(before, after):
    require(set(after['tables']) == set(before['tables']), 'Unexpected table addition/removal')
    require(before['roles'] == after['roles'] and before['owners'] == after['owners'], 'Database authority changed')
    require(before['schema'] == OLD and after['schema'] == HEAD, 'Unexpected schema upgrade')
    old_stock = before['tables']['stock_items']
    new_stock = after['tables']['stock_items']
    require('unit_cost' not in old_stock['columns'] and
            new_stock['columns'].get('unit_cost') == {'type': 'NUMERIC(12, 2)', 'nullable': True, 'default': None} and
            before['unit_cost_nonnull'] is None and after['unit_cost_nonnull'] == 0,
            'Master cost must be a new nullable NUMERIC(12,2) column with every existing value NULL')
    for table, original in before['tables'].items():
        retained = dict(after['tables'][table])
        if table == 'stock_items':
            retained['columns'] = {name: column for name, column in retained['columns'].items() if name != 'unit_cost'}
        require(original == retained, 'Retained row/column changed: ' + table)
    expected_flags = {id_: {'kind': 'service', 'stock_tracked': False} if flags['kind'] == 'product' else flags
                      for id_, flags in before['catalog_flags'].items()}
    require(after['catalog_flags'] == expected_flags, 'Unexpected catalogue kind/tracking change')
    converted = sum(flags['kind'] == 'product' for flags in before['catalog_flags'].values())
    require(after['business_revision'] == before['business_revision'] + converted,
            'Unexpected catalogue-trigger business revision increment')
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
                            'Expected current 0.4.7 schema and no existing maintenance')
                    connection.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'), {'job': args.job})
                    connection.commit()
                    result = snapshot(connection)
                else:
                    require(current['maintenance'] and current['maintenance_reset_id'] == args.job, 'Maintenance belongs to another job')
                    before = snapshot(connection)
                    require(args.baseline and before == json.loads(Path(args.baseline).read_text()), 'Checkpoint data changed')
                    if args.mode == 'migrate':
                        require(revision(connection) == OLD, 'Exact previous schema required')
                        from app.schema_maintenance import upgrade_ordering048_schema
                        upgrade_ordering048_schema(connection)
                        connection.execute(text('UPDATE alembic_version SET version_num=:head'), {'head': HEAD})
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
