"""Container startup preflight. Standalone: never import Flask or run recovery."""
import os
import stat
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def validate_environment(environment):
    for name in ('AUTO_CREATE_DB', 'RUN_MIGRATIONS', 'SEED_DEFAULTS'):
        if environment.get(name, '0') != '0':
            raise RuntimeError('Normal API startup forbids migration, seed and auto-create flags')
    for name in ('API_WORKERS', 'WEB_CONCURRENCY', 'API_REPLICAS'):
        if environment.get(name, '1') != '1':
            raise RuntimeError('Normal API requires one process and one replica')
    # Fixed service-private mount also rejects relative paths before normalization.
    if environment.get('RESET_PRIVATE_DIR') != '/var/lib/xiquan-reset':
        raise RuntimeError('Reset storage must use the private /var/lib/xiquan-reset mount')
    names = {'runtime': 'RUNTIME_DATABASE_URL', 'reset': 'RESET_DATABASE_URL',
             'backup': 'RESET_BACKUP_DATABASE_URL'}
    urls = {}
    try:
        for kind, name in names.items():
            url = make_url(environment.get(name, ''))
            if (url.drivername != 'postgresql+psycopg' or not url.host or not url.database
                    or not url.username or not url.password
                    or set(url.query) - {'sslmode', 'sslrootcert', 'sslcert', 'sslkey'}):
                raise ValueError('Invalid deployment URL')
            urls[kind] = url
        runtime = urls['runtime']
        if make_url(environment.get('DATABASE_URL', '')) != runtime:
            raise ValueError('Normal database URL must be runtime URL')
        def endpoint(url):
            return url.host, url.port or 5432, url.database
        if any(endpoint(url) != endpoint(runtime) for url in urls.values()):
            raise ValueError('Different endpoints')
        if len({url.username for url in urls.values()}) != 3 or urls['reset'].username != 'xiquan_reset':
            raise ValueError('Distinct identities required')
    except Exception:
        raise RuntimeError('Three distinct private PostgreSQL URLs for the same database are required') from None
    return urls


def validate_private_directory(path):
    directory = Path(path)
    info = directory.lstat()
    if (os.name != 'posix' or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid()
            or directory.resolve() != directory):
        raise RuntimeError('Private reset mount must be an app-owned Linux directory with mode 0700')


def validate_role_status(status, expected_identity):
    if (status['identity'] != expected_identity or status['server_major'] != 17
            or any(status[key] for key in (
                'privileged', 'member', 'owner', 'forbidden', 'missing_read', 'schema_create'
            ))):
        raise RuntimeError('PostgreSQL 17 dedicated nonowner role/grants validation failed')


def check_database_roles(urls, engine_factory=create_engine):
    common = """
        SELECT session_user::text AS identity,
          current_setting('server_version_num')::integer / 10000 AS server_major,
          (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
            OR current_user <> session_user) AS privileged,
          has_schema_privilege(session_user, 'public', 'CREATE') AS schema_create,
          EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid) AS member,
          (EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname = 'public'
                   AND pg_has_role(session_user, n.nspowner, 'MEMBER'))
           OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                      WHERE n.nspname = 'public' AND pg_has_role(session_user, c.relowner, 'MEMBER'))
           OR EXISTS (SELECT 1 FROM pg_database d WHERE d.datname = current_database()
                      AND pg_has_role(session_user, d.datdba, 'MEMBER'))) AS owner,
          EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f','S')
                    AND NOT CASE WHEN c.relkind = 'S' THEN has_sequence_privilege(session_user, c.oid, 'SELECT')
                        ELSE has_table_privilege(session_user, c.oid, 'SELECT') END) AS missing_read,
          {forbidden} AS forbidden
        FROM pg_roles r WHERE r.rolname = session_user
    """
    for kind, url in urls.items():
        if kind == 'runtime':
            scope = "c.relname IN ('business_state','business_periods','access_policies','reset_tasks','reset_events')"
            denied = "'INSERT,UPDATE,DELETE,TRUNCATE'"
            columns = "OR has_any_column_privilege(session_user, c.oid, 'INSERT,UPDATE')"
        elif kind == 'backup':
            scope = 'TRUE'
            denied = "'INSERT,UPDATE,DELETE,TRUNCATE'"
            columns = "OR has_any_column_privilege(session_user, c.oid, 'INSERT,UPDATE')"
        else:
            scope = 'TRUE'
            denied = "'DELETE,TRUNCATE'"
            columns = """OR (c.relname = 'access_policies' AND
              (has_table_privilege(session_user, c.oid, 'INSERT,UPDATE')
               OR has_any_column_privilege(session_user, c.oid, 'INSERT,UPDATE')))"""
        forbidden = f"""EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
          WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f') AND ({scope})
          AND (has_table_privilege(session_user, c.oid, {denied}) {columns}))"""
        engine = None
        try:
            engine = engine_factory(url, connect_args={'options': '-c default_transaction_read_only=on'},
                                    hide_parameters=True)
            with engine.connect() as connection:
                result = connection.execute(text(common.format(forbidden=forbidden))).mappings().one()
                validate_role_status(result, url.username)
        except Exception:
            # Never emit a driver exception, DSN, password, or SQL parameter.
            raise RuntimeError('Private database role preflight failed; inspect roles/grants locally') from None
        finally:
            if engine is not None:
                engine.dispose()


def main():
    try:
        urls = validate_environment(os.environ)
        validate_private_directory(os.environ['RESET_PRIVATE_DIR'])
        check_database_roles(urls)
    except Exception:
        print(
            '[xiquan] Startup preflight failed: verify private URLs, Linux0700 mount, PG17 roles/grants.',
            file=sys.stderr,
        )
        return 1
    print('[xiquan] Read-only deployment preflight passed; owner maintenance remains explicit.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
