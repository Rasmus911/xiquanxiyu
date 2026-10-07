"""Private, verified full-database snapshots. Never exposed through HTTP."""
import hashlib
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from flask import current_app
from sqlalchemy import inspect, select
from sqlalchemy.engine import make_url

from .models import AuditLog


@dataclass(frozen=True)
class BackupResult:
    private_path: str
    sha256: str
    size: int
    schema_version: str
    audit_checkpoint: dict


def private_directory(kind):
    configured = current_app.config.get('RESET_PRIVATE_DIR')
    if not configured:
        raise RuntimeError('RESET_PRIVATE_DIR must be explicitly configured')
    root = Path(configured).resolve()
    if current_app.static_folder and root.is_relative_to(Path(current_app.static_folder).resolve()):
        raise RuntimeError('Reset storage must not be a public directory')
    path = root / kind
    for directory in (root, path):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise RuntimeError('Private storage cannot be a symlink')
        if os.name == 'nt':
            account = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
            subprocess.run(['icacls', str(directory), '/inheritance:r', '/grant:r',
                            f'{account}:(OI)(CI)F'], capture_output=True, check=True)
        else:
            directory.chmod(0o700)
    return path


def _pg_backup(connection, target):
    if connection.exec_driver_sql('SHOW server_version_num').scalar_one()[:2] != '17':
        raise RuntimeError('Backup requires PostgreSQL 17')
    url = make_url(current_app.config.get('RESET_BACKUP_DATABASE_URL') or '')
    source = connection.engine.url
    if (not url.drivername.startswith('postgresql') or
            (url.host, url.port or 5432, url.database) != (source.host, source.port or 5432, source.database)):
        raise RuntimeError('A dedicated read-only backup URL for the same database is required')
    binaries = [current_app.config.get('PG_DUMP_PATH', 'pg_dump'),
                current_app.config.get('PG_RESTORE_PATH', 'pg_restore')]
    for binary in binaries:
        version = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True)
        if not re.search(r'\b17\.\d+', version.stdout):
            raise RuntimeError('PostgreSQL 17 client tools are required')
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME'}}
    env.update(PGHOST=url.host or 'localhost', PGPORT=str(url.port or 5432),
               PGDATABASE=url.database, PGUSER=url.username or '', PGPASSWORD=url.password or '',
               PGAPPNAME='xiquan-private-backup', PGOPTIONS='-c default_transaction_read_only=on')
    for key in ('sslmode', 'sslrootcert', 'sslcert', 'sslkey'):
        if url.query.get(key):
            env['PG' + key.upper()] = str(url.query[key])
    # Credentials are only in the child's private environment, never argv/logs.
    subprocess.run([binaries[0], '--format=custom', '--no-password', '--file', str(target)],
                   env=env, capture_output=True, check=True, timeout=1800)
    subprocess.run([binaries[1], '--list', str(target)], env=env, capture_output=True,
                   check=True, timeout=60)


def create_database_backup(connection, reset_id, period_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', reset_id):
        raise ValueError('Invalid reset ID')
    directory = private_directory('backups')
    target = directory / f'{reset_id}-{uuid4().hex}.partial'
    final = target.with_suffix('.backup')
    try:
        if connection.dialect.name == 'sqlite':
            source = connection.engine.url.database
            if not source or source == ':memory:':
                raise RuntimeError('A file database is required for a recoverable SQLite backup')
            with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as reader:
                with closing(sqlite3.connect(target)) as writer:
                    reader.backup(writer)
                    if writer.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('SQLite backup integrity check failed')
        elif connection.dialect.name == 'postgresql':
            _pg_backup(connection, target)
        else:
            raise RuntimeError('Unsupported database')
        size = target.stat().st_size
        if size == 0:
            raise RuntimeError('Empty backup')
        digest = hashlib.sha256()
        with target.open('r+b') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
            os.fsync(stream.fileno())
        last = connection.execute(select(AuditLog.chain_index, AuditLog.current_hash)
                                  .order_by(AuditLog.chain_index.desc()).limit(1)).first()
        version = 'metadata-create-all'
        if inspect(connection).has_table('alembic_version'):
            version = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
        target.replace(final)
        return BackupResult(str(final), digest.hexdigest(), size, version,
                            {'period_id': period_id, 'chain_index': last[0] if last else 0,
                             'current_hash': last[1] if last else '0' * 64})
    except Exception:
        target.unlink(missing_ok=True)
        raise
