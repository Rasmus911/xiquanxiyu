"""Additive 0.4.7 guard: retain rows, quantities, money, identities and audit evidence."""
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

OLD = '20261007_desktop_ops'
HEAD = '20261007_insights_cost'


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
        if table in ('stock_items','catalog_items'):
            projection += " - 'low_stock_threshold'"
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
    from app.stock_cost_service import warning_quantity
    from app.models import StockItem, StockMovement, InventoryMovement
    from sqlalchemy import select
    actual, expected = {}, {}
    movement = StockMovement.__table__; legacy = InventoryMovement.__table__
    for row in connection.execute(select(StockItem.__table__)).mappings():
        quantity = connection.execute(select(movement.c.quantity).where(
            movement.c.stock_item_id==row['id'],movement.c.movement_type.in_(('purchase','opening')),
            movement.c.quantity>0).order_by(movement.c.created_at.desc(),movement.c.id.desc()).limit(1)).scalar_one_or_none()
        if quantity is None and row['legacy_catalog_item_id']:
            quantity = connection.execute(select(legacy.c.quantity).where(
                legacy.c.catalog_item_id==row['legacy_catalog_item_id'],legacy.c.quantity>0,
                legacy.c.movement_type.in_(('purchase','opening'))).order_by(
                legacy.c.created_at.desc(),legacy.c.id.desc()).limit(1)).scalar_one_or_none()
        expected[row['id']] = str(warning_quantity(quantity if quantity is not None else row['stock_quantity']))
        actual[row['id']] = f"{row['low_stock_threshold']:.3f}"
        if row['legacy_catalog_item_id']:
            id_ = row['legacy_catalog_item_id']
            expected['catalog:'+id_] = expected[row['id']]
            actual['catalog:'+id_] = f"{connection.execute(text('SELECT low_stock_threshold FROM catalog_items WHERE id=:id'),{'id':id_}).scalar_one():.3f}"
    markers = list(connection.exec_driver_sql('SELECT revision FROM schema_upgrade_markers ORDER BY revision').scalars()) if 'schema_upgrade_markers' in tables else []
    return {'tables': tables, 'roles': role_hash, 'owners': owners, 'audit_valid': True,
            'alerts_expected':expected,'alerts_actual':actual,'schema':version,'markers':markers}


def compare(before, after):
    additions = {'stock_costs','schema_upgrade_markers'}
    require(set(after['tables']) == set(before['tables']) | additions, 'Unexpected table addition/removal')
    require(before['roles'] == after['roles'] and all(after['owners'].get(name)==owner for name,owner in before['owners'].items()), 'Database authority changed')
    for table in before['tables']:
        require(before['tables'][table] == after['tables'][table], 'Retained row/column changed: ' + table)
    require(before['schema']==OLD and after['schema']==HEAD, 'Unexpected schema upgrade')
    require(after['alerts_actual']==before['alerts_expected'], 'Automatic alert values differ')
    require(after['tables']['stock_costs']['rows']==0 and after['markers']==[HEAD], 'Unexpected new cost/marker evidence')
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
                            'Expected current 0.4.6 schema and no existing maintenance')
                    connection.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'), {'job':args.job})
                    connection.commit()
                    result = snapshot(connection)
                else:
                    require(current['maintenance'] and current['maintenance_reset_id'] == args.job, 'Maintenance belongs to another job')
                    before = snapshot(connection)
                    require(args.baseline and before == json.loads(Path(args.baseline).read_text()), 'Checkpoint data changed')
                    if args.mode == 'migrate':
                        require(revision(connection) == OLD, 'Exact previous schema required')
                        from app.schema_maintenance import upgrade_insights047_schema
                        upgrade_insights047_schema(connection)
                        connection.execute(text('UPDATE alembic_version SET version_num=:head'),{'head':HEAD})
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
