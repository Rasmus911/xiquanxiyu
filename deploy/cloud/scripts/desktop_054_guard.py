"""Exact additive 0.5.4 guard. Evidence contains hashes, never business rows."""
import argparse
import copy
import importlib
import json
import re
import uuid
from pathlib import Path

from sqlalchemy import inspect, text

OLD = '20261012_physical_membership'
HEAD = '20261013_wristband_chip'
NEW = {'wristband_chip_bindings', 'wristband_scan_sessions'}
STATE_COLUMNS = {'is_active', 'revoked_at', 'replaced_by_id', 'version', 'updated_at'}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def require_isolated(url):
    require(bool(url.host) and url.host.startswith('xiquan-operations-restore-') and
            url.database == 'operations_restore', 'Writes require an isolated restore endpoint')


def row_projection(table):
    require(re.fullmatch('[a-z][a-z0-9_]*', table), 'Unexpected identifier')
    excluded = {'alembic_version': 'version_num'}.get(table)
    return 'to_jsonb(t)' + (" - '" + excluded + "'" if excluded else '')


def prove_runtime_roles(connection):
    """Inspect effective PG privileges, including inherited and column grants."""
    require(int(connection.exec_driver_sql('SHOW server_version_num').scalar_one()) // 10000 == 17, 'PG17 required')
    result = {}
    for role in ('xiquan_app', 'xiquan_reset', 'xiquan_backup'):
        flags = connection.execute(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls '
                                        'FROM pg_roles WHERE rolname=:role'), {'role': role}).scalar_one()
        require(not flags, 'Privileged runtime role')
        require(not connection.execute(text('SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member '
                                            'WHERE r.rolname=:role'), {'role': role}).first(), 'Inherited runtime role')
        tables = {}
        for table in sorted(NEW):
            allowed = {column['name'] for column in inspect(connection).get_columns(table)} if role == 'xiquan_app' else set()
            privileges = {}
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'):
                actual = connection.execute(text('SELECT has_table_privilege(:role,:table,:privilege)'),
                                            dict(role=role, table=table, privilege=privilege)).scalar_one()
                expected = privilege == 'SELECT' or (role == 'xiquan_app' and privilege in ('INSERT', 'UPDATE'))
                require(actual == expected, 'Unexpected table privilege')
                privileges[privilege] = actual
            writable = []
            for column in inspect(connection).get_columns(table):
                actual = connection.execute(text("SELECT has_column_privilege(:role,:table,:column,'UPDATE')"),
                                            dict(role=role, table=table, column=column['name'])).scalar_one()
                require(actual == (column['name'] in allowed), 'Unexpected column privilege')
                if actual: writable.append(column['name'])
            tables[table] = dict(privileges=privileges, update_columns=sorted(writable))
        result[role] = tables
    return dict(verified=True, roles=result)


def table_owners(connection):
    return dict(connection.exec_driver_sql("""SELECT c.relname,pg_get_userbyid(c.relowner) FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p')""").all())


def snapshot(session):
    """Accept a SQLAlchemy Connection or Session; take inside one transaction."""
    connection = session if hasattr(session, 'exec_driver_sql') else session.connection()
    version = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
    require(version in (OLD, HEAD), 'Unexpected schema revision')
    require(int(connection.exec_driver_sql('SHOW server_version_num').scalar_one()) // 10000 == 17, 'PG17 required')
    connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
    connection.exec_driver_sql("SET LOCAL DateStyle='ISO,YMD'")
    connection.exec_driver_sql("SET LOCAL IntervalStyle='postgres'")
    connection.exec_driver_sql('SET LOCAL extra_float_digits=3')
    inspector = inspect(connection)
    hashes, counts, columns, foreign_keys, indexes = {}, {}, {}, {}, {}
    for name in sorted(inspector.get_table_names(schema='public')):
        projection = row_projection(name)
        columns[name] = {c['name']: dict(type=str(c['type']), nullable=c['nullable'], default=c['default'])
                         for c in inspector.get_columns(name)}
        if name in NEW:
            counts[name] = connection.exec_driver_sql(f'SELECT count(*) FROM public."{name}"').scalar_one()
        else:
            count, digest = connection.exec_driver_sql(f'''SELECT count(*), encode(sha256(convert_to(
                COALESCE(string_agg(({projection})::text,E'\\n' ORDER BY ({projection})::text COLLATE "C"),''),
                'UTF8')),'hex') FROM public."{name}" t''').one()
            hashes[name] = dict(rows=count, sha256=digest)
        foreign_keys[name] = sorted([dict(columns=fk['constrained_columns'], table=fk['referred_table'],
            referred=fk['referred_columns'], options=fk['options']) for fk in inspector.get_foreign_keys(name)], key=str)
        indexes[name] = [list(row) for row in connection.execute(text('SELECT indexname,indexdef FROM pg_indexes '
                           "WHERE schemaname='public' AND tablename=:name ORDER BY indexname"), dict(name=name))]
    roles = connection.exec_driver_sql("""SELECT encode(sha256(convert_to(string_agg(row_to_json(r)::text,
        E'\n' ORDER BY rolname),'UTF8')),'hex') FROM pg_authid r
        WHERE rolname IN ('xiquan_app','xiquan_reset','xiquan_backup')""").scalar_one()
    owners = table_owners(connection)
    grants = {name: list(acl) for name, acl in connection.exec_driver_sql("""SELECT c.relname,
        ARRAY(SELECT a::text FROM unnest(COALESCE(c.relacl,acldefault('r',c.relowner))) a ORDER BY a::text)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p')""")}
    from app.operations_backup import _verify_snapshot_audit
    require(_verify_snapshot_audit(connection), 'Audit evidence invalid')
    return dict(schema_revision=version, old_row_hashes=hashes, new_row_counts=counts, columns=columns,
                foreign_keys=foreign_keys, indexes=indexes, roles=roles, owners=owners, grants=grants,
                audit_valid=True, runtime_roles=prove_runtime_roles(connection) if version == HEAD else None,
                control_state=dict(connection.exec_driver_sql('SELECT * FROM business_state WHERE id=1').mappings().one()))


def compare_migration(before, after):
    require(before['schema_revision'] == OLD and after['schema_revision'] == HEAD, 'Wrong migration edge')
    require(not before['new_row_counts'] and set(after['new_row_counts']) == NEW and
            all(value == 0 for value in after['new_row_counts'].values()), 'Unexpected tables or new rows')
    require(before['old_row_hashes'] == after['old_row_hashes'], 'Retained data changed')
    require(before['roles'] == after['roles'], 'Roles changed')
    require(before['audit_valid'] and after['audit_valid'], 'Audit invalid')
    for table in before['old_row_hashes']:
        expected = copy.deepcopy(before['columns'][table])
        require(expected == after['columns'][table], 'Retained columns changed')
        for key in ('owners', 'grants', 'foreign_keys', 'indexes'):
            require(before[key][table] == after[key][table], 'Retained ' + key + ' changed')
    require(all(after['owners'][n] == before['owners']['members'] for n in NEW), 'New ownership differs')
    require(after['runtime_roles']['verified'] is True, 'Runtime privilege proof missing')


def migrate(connection):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(connection)):
        importlib.import_module('migrations.versions.' + HEAD).upgrade()
    connection.execute(text('UPDATE alembic_version SET version_num=:head'), dict(head=HEAD))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['inspect', 'claim', 'migrate', 'release', 'proof'])
    parser.add_argument('--job', required=True)
    parser.add_argument('--baseline')
    args = parser.parse_args()
    require(str(uuid.UUID(args.job)) == args.job, 'Invalid job')
    from app import create_app
    from app.extensions import db
    from app.business_barrier import exclusive_barrier
    from app.operations_upgrade import maintenance_connection
    from stock_guard import roles, state, revision
    app = create_app()
    with app.app_context(), maintenance_connection() as connection:
        if args.mode == 'proof':
            from desktop_054_pgproof import exercise
            result = exercise(app, connection, args.job)
        elif args.mode == 'inspect':
            if not (db.engine.url.host or '').startswith('xiquan-operations-restore-'): roles()
            result = snapshot(connection)
        else:
            with exclusive_barrier(connection, args.job):
                current = state(connection)
                require(not connection.exec_driver_sql("SELECT count(*) FROM reset_tasks WHERE status IN ('queued','running')").scalar_one(), 'Pending reset')
                before = snapshot(connection)
                require(args.baseline and before == json.loads(Path(args.baseline).read_text()), 'Exact baseline changed')
                if args.mode == 'claim':
                    require(revision(connection) == OLD and not current['maintenance'] and not current['maintenance_reset_id'], 'Unexpected maintenance')
                    connection.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'), dict(job=args.job))
                    result = snapshot(connection)
                else:
                    require(current['maintenance'] and current['maintenance_reset_id'] == args.job, 'Maintenance is not owned')
                    if args.mode == 'migrate':
                        require(revision(connection) == OLD, 'Exact predecessor required')
                        migrate(connection)
                        result = snapshot(connection)
                        compare_migration(before, result)
                    else:
                        require(revision(connection) == HEAD, 'New schema required')
                        connection.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
                        result = dict(released=True, schema=HEAD, owner=args.job)
                connection.commit()
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Parent captures traceback in a 0600 file, never forwards it publicly.
        raise
