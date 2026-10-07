"""Private snapshot/restore evidence. Never registered as an HTTP operation."""
import hashlib
import json
import os
import re
import stat
import subprocess
import hmac
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

import click
from flask import current_app
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url

from .models import AuditLog, BusinessStateModel


class BackupReceiptError(ValueError):
    pass


def snapshot_identity(connection):
    state = connection.execute(select(BusinessStateModel.__table__)).mappings().one()
    last = connection.execute(select(AuditLog.chain_index, AuditLog.current_hash)
        .order_by(AuditLog.chain_index.desc()).limit(1)).first()
    revision = 'metadata-create-all'
    if inspect(connection).has_table('alembic_version'):
        revision = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
    return dict(db_name=connection.engine.url.database or ':memory:', alembic_revision=revision,
        business_period_id=state['period_id'], business_revision=state['business_revision'],
        audit_checkpoint=dict(chain_index=last[0] if last else 0, current_hash=last[1] if last else '0'*64))


def _check_windows_acl(path):
    # A literal path passed through a private child environment, never interpolated
    # into script source. Deny broad readers as well as writers of private dumps.
    script = """$ErrorActionPreference='Stop'
$acl=Get-Acl -LiteralPath $env:XIQUAN_RECEIPT_ACL_PATH
$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed=@($sid,'S-1-5-18','S-1-5-32-544')
$owner=$acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
if ($owner -notin $allowed) { exit 2 }
$allowed+= 'S-1-3-4' # OWNER RIGHTS resolves only to the already verified owner.
foreach ($rule in $acl.Access) {
  if ($rule.AccessControlType -eq 'Allow' -and
      $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -notin $allowed) { exit 3 }
}
"""
    env = os.environ.copy()
    env['XIQUAN_RECEIPT_ACL_PATH'] = str(path)
    # A Core PowerShell parent can export incompatible module manifests.
    env['PSModulePath'] = str(Path(env.get('SYSTEMROOT','C:\\Windows')) / 'System32' /
        'WindowsPowerShell' / 'v1.0' / 'Modules')
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        env=env, capture_output=True, timeout=20)
    if result.returncode:
        raise BackupReceiptError('Private storage ACL must allow only its owner, SYSTEM and administrators')


def private_path(path, *, directory=False):
    configured = current_app.config.get('RESET_PRIVATE_DIR')
    if not configured:
        raise BackupReceiptError('Private backup storage is not configured')
    root = Path(configured).absolute()
    target = Path(path).absolute()
    if '..' in root.parts or '..' in target.parts:
        raise BackupReceiptError('Parent traversal is forbidden in private evidence paths')
    try:
        target.relative_to(root)
    except ValueError:
        raise BackupReceiptError('Backup evidence must remain inside private storage') from None
    # Check before resolve: resolving a symlink first would hide its provenance.
    for candidate in [*root.parents, root]:
        if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
            raise BackupReceiptError('Private storage cannot contain symlinks or junctions')
    for candidate in [root, *list(target.parents)[:len(target.relative_to(root).parts)-1], target]:
        if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
            raise BackupReceiptError('Private storage cannot contain symlinks or junctions')
        try:
            info = candidate.stat()
        except OSError:
            raise BackupReceiptError('Private backup evidence is missing') from None
        if os.name == 'nt':
            _check_windows_acl(candidate)
        elif info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise BackupReceiptError('Backup files require owner-only permissions')
    if (directory and not target.is_dir()) or (not directory and not target.is_file()):
        raise BackupReceiptError('Invalid private backup file type')
    if current_app.static_folder and target.resolve().is_relative_to(Path(current_app.static_folder).resolve()):
        raise BackupReceiptError('Backup evidence cannot be served publicly')
    return target


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BackupReceiptError('Backup changed while being verified')
    return digest.hexdigest(), after.st_size


def validate_backup_receipt(connection, receipt_path: Path, expected_revision: str):
    path = private_path(receipt_path)
    try:
        if path.stat().st_size > 256*1024:
            raise ValueError
        data = json.loads(path.read_text(encoding='utf-8'))
        restore = data.get('restore', {})
        if (data.get('schema') != 1 or restore.get('status') != 'verified'
                or restore.get('pg_major') != 17 or not re.fullmatch('[0-9a-f]{64}', restore.get('checks_sha256',''))):
            raise ValueError
        checked = datetime.fromisoformat(restore['checked_at'])
        if checked.tzinfo is None or checked > datetime.now(timezone.utc):
            raise ValueError
        identity = snapshot_identity(connection)
        if identity['alembic_revision'] != expected_revision or any(data.get(key) != value for key,value in identity.items()):
            raise ValueError
        dump = private_path(data['dump_path'])
        digest, size = file_digest(dump)
        if size <= 0 or type(data['dump_size']) is not int or (digest,size) != (data['dump_sha256'],data['dump_size']):
            raise ValueError
    except (ValueError, TypeError, KeyError, OSError):
        raise BackupReceiptError('Backup receipt is unverified, changed or does not match the current database') from None
    return data


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def write_private_json(path, data):
    """Exclusive creation, never replace an earlier attempt or verified receipt."""
    target = Path(path)
    private_path(target.parent, directory=True)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(target, flags, 0o600)
    except OSError:
        raise BackupReceiptError('Private evidence output already exists or is inaccessible') from None
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(_canonical(data) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == 'nt':
        _check_windows_acl(target)
    return target


def compose_verified_receipt(candidate, live_source, restored):
    """Only exact row/snapshot agreement on a physically separate PG17 cluster passes."""
    if candidate.get('schema') != 1 or candidate.get('restore', {}).get('status') != 'pending':
        raise BackupReceiptError('A pending snapshot, not a reused or list-only receipt, is required')
    if candidate.get('checks') != live_source:
        raise BackupReceiptError('Source database changed since the snapshot; create a new backup')
    source_server, restore_server = live_source['server'], restored['server']
    if (source_server.get('pg_major') != 17 or restore_server.get('pg_major') != 17
            or not source_server.get('system_identifier') or not restore_server.get('system_identifier')
            or source_server['system_identifier'] == restore_server['system_identifier']):
        raise BackupReceiptError('Restore must use an actual isolated PostgreSQL 17 server')
    identities = [dict(value['identity']) for value in (live_source, restored)]
    for identity in identities:
        identity.pop('db_name', None)
    if (identities[0] != identities[1] or live_source['tables'] != restored['tables']
            or live_source.get('totals') != restored.get('totals')
            or not live_source.get('audit_valid') or not restored.get('audit_valid')):
        raise BackupReceiptError('Restored schema, rows, balances, stock or audit evidence differs')
    if any(candidate.get(key) != value for key, value in live_source['identity'].items()):
        raise BackupReceiptError('Candidate identity changed since the snapshot')
    result = {key: candidate[key] for key in ('schema', 'dump_path', 'dump_sha256', 'dump_size')}
    result.update(live_source['identity'])
    result['restore'] = dict(status='verified', pg_major=17,
        source_server_id=source_server['system_identifier'],
        restored_server_id=restore_server['system_identifier'],
        checked_at=datetime.now(timezone.utc).isoformat(),
        checks_sha256=hashlib.sha256(_canonical(restored).encode('utf-8')).hexdigest())
    return result


def _postgres_snapshot_begin(connection):
    if connection.dialect.name != 'postgresql':
        raise BackupReceiptError('Actual PostgreSQL 17 restore evidence is required, not SQLite')
    connection.rollback()
    connection.execution_options(isolation_level='REPEATABLE READ')
    connection.exec_driver_sql('SET TRANSACTION READ ONLY')
    connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
    connection.exec_driver_sql("SET LOCAL DateStyle = 'ISO, YMD'")
    connection.exec_driver_sql("SET LOCAL IntervalStyle = 'postgres'")
    connection.exec_driver_sql('SET LOCAL extra_float_digits = 3')


def _verify_snapshot_audit(connection):
    from .audit_service import _canonical_json, _payload, sign_evidence
    previous, index, strong = '0' * 64, 1, False
    rows = connection.execute(select(AuditLog.__table__).order_by(AuditLog.chain_index))
    for row in rows.mappings():
        item = SimpleNamespace(**row)
        if item.integrity_version == 2:
            strong = True
            expected = sign_evidence(_payload(item))
        elif item.integrity_version == 1 and not strong:
            expected = hashlib.sha256(_canonical_json(_payload(item)).encode('utf-8')).hexdigest()
        else:
            return False
        if item.chain_index != index or item.prev_hash != previous or not hmac.compare_digest(item.current_hash, expected):
            return False
        previous, index = item.current_hash, index + 1
    return True


def collect_snapshot_checks(connection):
    """Stream canonical row hashes for EVERY public table; never emit raw rows."""
    if connection.dialect.name != 'postgresql':
        raise BackupReceiptError('Snapshot checks require PostgreSQL 17')
    server = connection.exec_driver_sql('SELECT system_identifier::text FROM pg_control_system()').scalar_one()
    major = int(connection.exec_driver_sql('SHOW server_version_num').scalar_one()) // 10000
    database = connection.exec_driver_sql('SELECT current_database()').scalar_one()
    if major != 17:
        raise BackupReceiptError('PostgreSQL 17 is required')
    tables = {}
    preparer = connection.dialect.identifier_preparer
    for name in sorted(inspect(connection).get_table_names(schema='public')):
        table = 'public.' + preparer.quote(name)
        # COLLATE C makes ordering independent of the two clusters' locale.
        rows = connection.exec_driver_sql(
            f'SELECT to_jsonb(t)::text AS row_json FROM {table} AS t ORDER BY (to_jsonb(t)::text) COLLATE "C"',
            execution_options={'stream_results': True})
        digest, count = hashlib.sha256(), 0
        for row in rows:
            digest.update(row[0].encode('utf-8') + b'\n')
            count += 1
        rows.close()
        tables[name] = dict(rows=count, sha256=digest.hexdigest())
    totals = {}
    for table, column, label in (('members', 'balance', 'member_balance'),
            ('member_passes', 'remaining_count', 'remaining_pass_uses'),
            ('catalog_items', 'stock_quantity', 'stock_quantity'),
            ('settlements', 'paid_amount', 'settlement_paid')):
        value = connection.exec_driver_sql(f'SELECT COALESCE(sum({column}),0) FROM public.{table}').scalar_one()
        totals[label] = str(value)
    return dict(server=dict(system_identifier=str(server), pg_major=major, database=database),
        identity=snapshot_identity(connection), tables=tables, totals=totals,
        audit_valid=_verify_snapshot_audit(connection))


def run_snapshot_dump(source_url, exported_snapshot, target):
    """Keep the owner's exported transaction open while read-only pg_dump imports it."""
    try:
        url = make_url(current_app.config.get('RESET_BACKUP_DATABASE_URL') or '')
        endpoint = lambda value: (value.host, value.port or 5432, value.database)
        if (url.drivername != 'postgresql+psycopg' or endpoint(url) != endpoint(source_url)
                or not url.username or not url.password or url.username == source_url.username
                or set(url.query) - {'sslmode', 'sslrootcert', 'sslcert', 'sslkey'}):
            raise ValueError
        if not re.fullmatch('[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', exported_snapshot):
            raise ValueError
    except Exception:
        raise BackupReceiptError('A dedicated read-only backup connection and exported snapshot are required') from None
    dump = current_app.config['PG_DUMP_PATH']
    restore = current_app.config['PG_RESTORE_PATH']
    environment = {key: value for key, value in os.environ.items()
        if key in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME'}}
    environment.update(PGHOST=url.host, PGPORT=str(url.port or 5432), PGDATABASE=url.database,
        PGUSER=url.username, PGPASSWORD=url.password, PGAPPNAME='xiquan-operations-snapshot',
        PGOPTIONS='-c default_transaction_read_only=on')
    for key, value in url.query.items():
        environment['PG' + key.upper()] = str(value)
    try:
        for binary in (dump, restore):
            version = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True, timeout=20)
            if not re.search(r'\b17\.\d+', version.stdout):
                raise ValueError
        subprocess.run([dump, '--format=custom', '--no-owner', '--no-acl', '--no-password',
            '--snapshot=' + exported_snapshot, '--file', str(target)], env=environment,
            capture_output=True, check=True, timeout=1800)
        # This is only a format check, NEVER a verified restore status.
        subprocess.run([restore, '--list', str(target)], env=environment,
            capture_output=True, check=True, timeout=60)
    except Exception:
        raise BackupReceiptError('PostgreSQL 17 snapshot backup failed; private credentials were not logged') from None


def create_operations_snapshot(output):
    from .operations_upgrade import maintenance_connection
    output = Path(output)
    private_path(output, directory=True)
    target = output / 'database.backup'
    if any((output / name).exists() for name in ('database.backup', 'candidate.json', 'receipt.json')):
        raise BackupReceiptError('Snapshot attempt directory must be fresh')
    with maintenance_connection() as connection:
        _postgres_snapshot_begin(connection)
        exported = connection.exec_driver_sql('SELECT pg_export_snapshot()').scalar_one()
        checks = collect_snapshot_checks(connection)
        if not checks['audit_valid']:
            raise BackupReceiptError('Audit chain verification failed; no verified backup may be produced')
        with target.open('xb'):
            os.chmod(target, 0o600)
        run_snapshot_dump(connection.engine.url, exported, target)
        digest, size = file_digest(target)
        if size <= 0:
            raise BackupReceiptError('Snapshot dump is empty')
        candidate = dict(schema=1, **checks['identity'], dump_path=str(target), dump_sha256=digest,
            dump_size=size, checks=checks, restore=dict(status='pending'))
        write_private_json(output / 'candidate.json', candidate)
        connection.rollback()
    return dict(candidate_path=str(output / 'candidate.json'), dump_sha256=digest, dump_size=size,
        restore_status='pending', table_count=len(checks['tables']))


def verify_operations_restore(candidate_path, restore_url):
    from .operations_upgrade import maintenance_connection
    candidate_path = private_path(candidate_path)
    if candidate_path.stat().st_size > 1024 * 1024:
        raise BackupReceiptError('Snapshot evidence exceeds the private format limit')
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    dump = private_path(candidate['dump_path'])
    if file_digest(dump) != (candidate['dump_sha256'], candidate['dump_size']):
        raise BackupReceiptError('Snapshot dump changed before restore verification')
    engine = None
    try:
        url = make_url(restore_url)
        if (url.drivername != 'postgresql+psycopg' or not url.host or not url.database
                or not url.username or not url.password):
            raise ValueError
        engine = create_engine(url, hide_parameters=True)
        with maintenance_connection() as source, engine.connect() as restored:
            _postgres_snapshot_begin(source)
            _postgres_snapshot_begin(restored)
            # Real server IDs are compared, not merely the two connection strings.
            source_checks = collect_snapshot_checks(source)
            restored_checks = collect_snapshot_checks(restored)
            verified = compose_verified_receipt(candidate, source_checks, restored_checks)
            write_private_json(candidate_path.parent / 'restored-checks.json', restored_checks)
            write_private_json(candidate_path.parent / 'receipt.json', verified)
            source.rollback()
            restored.rollback()
    except BackupReceiptError:
        raise
    except Exception:
        raise BackupReceiptError('Restore verification failed; no deployment receipt was authorized') from None
    finally:
        if engine is not None:
            engine.dispose()
    return dict(receipt_path=str(candidate_path.parent / 'receipt.json'), restore_status='verified',
        tables_verified=len(restored_checks['tables']), checks_sha256=verified['restore']['checks_sha256'])


def register_operations_backup_cli(app):
    @app.cli.group('operations-backup')
    def backup_cli():
        """Explicit private owner maintenance; never start workers or HTTP."""

    def require_maintenance():
        if not current_app.config.get('MAINTENANCE_PROCESS'):
            raise click.ClickException('Explicit maintenance process is required')

    @backup_cli.command('create')
    @click.option('--output', required=True, type=click.Path(path_type=Path))
    def create_command(output):
        require_maintenance()
        try:
            result = create_operations_snapshot(output)
        except Exception:
            raise click.ClickException('Private snapshot failed; inspect maintenance configuration, tools and audit chain') from None
        click.echo(_canonical(result))

    @backup_cli.command('verify-restored')
    @click.option('--database-url-env', required=True)
    @click.option('--receipt', required=True, type=click.Path(exists=True, path_type=Path))
    def verify_command(database_url_env, receipt):
        require_maintenance()
        if database_url_env != 'XIQUAN_RESTORE_DATABASE_URL':
            raise click.ClickException('Only the dedicated isolated restore environment is accepted')
        try:
            result = verify_operations_restore(receipt, os.environ.get(database_url_env, ''))
        except Exception:
            raise click.ClickException('Private restore verification failed; no verified receipt was generated') from None
        click.echo(_canonical(result))
