"""Private PG17 restore orchestration. No published ports, no production restore."""
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import quote


class DeploymentError(ValueError):
    pass


def run(argv, *, input_file=None, timeout=1800):
    try:
        with input_file.open('rb') if input_file else __import__('contextlib').nullcontext(None) as stream:
            result = subprocess.run(argv, stdin=stream, capture_output=True, text=True,
                check=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        # Docker/driver failures can contain a resolved secret; never echo them.
        raise DeploymentError('External maintenance command failed; secrets were not printed') from None


def write_environment(path, variables):
    if any(not re.fullmatch('[A-Z][A-Z0-9_]*', key) or any(c in str(value) for c in '\r\n\0')
           for key, value in variables.items()):
        raise DeploymentError('Private environment contains an unsupported value')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as writer:
            writer.write(''.join(f'{key}={value}\n' for key, value in sorted(variables.items())))
    except OSError:
        raise DeploymentError('Private environment output already exists or is inaccessible') from None


def wait_healthy(name, timeout=150, *, runner=None):
    runner = runner or run
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = json.loads(runner(['docker', 'inspect', name], timeout=20))[0]
        status = info['State'].get('Health', {}).get('Status')
        if info['State'].get('Running') and status == 'healthy': return
        if not info['State'].get('Running') or status == 'unhealthy':
            raise DeploymentError('A maintenance container did not become healthy')
        time.sleep(2)
    raise DeploymentError('Maintenance health check timed out')


def inspect_database(container, *, legacy_projection=False, runner=None):
    """Exact hashes of all public rows, without returning passwords or customer data."""
    runner = runner or run
    prefix = "BEGIN READ ONLY; SET LOCAL TIME ZONE 'UTC'; SET LOCAL DateStyle='ISO,YMD'; "
    prefix += "SET LOCAL IntervalStyle='postgres'; SET LOCAL extra_float_digits=3; "
    shell = 'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"'
    def query(sql):
        return json.loads(runner(['docker', 'exec', container, 'sh', '-eu', '-c', shell,
            'sh', prefix + sql + '; ROLLBACK;'], timeout=120))
    info = query("SELECT json_build_object('pg_major',current_setting('server_version_num')::integer/10000,"
                 "'system_identifier',(SELECT system_identifier::text FROM pg_control_system()))")
    names = query("SELECT COALESCE(json_agg(tablename ORDER BY tablename),'[]'::json) FROM pg_tables WHERE schemaname='public'")
    tables = {}
    new_columns = {'employees':['allowed_channels','deleted_at'], 'wristbands':['bath_area','is_active'],
        'catalog_items':['reference_code','package_definition'],
        'order_items':['covered_quantity','package_order_item_id','package_snapshot']}
    for name in names:
        if not re.fullmatch('[a-z][a-z0-9_]*', name):
            raise DeploymentError('Unexpected public table identifier')
        row_json = 'to_jsonb(t)'
        if legacy_projection and name in new_columns:
            row_json += ' - ARRAY[' + ','.join("'" + column + "'" for column in new_columns[name]) + ']::text[]'
        text = '(' + row_json + ')::text'
        tables[name] = query(f"SELECT json_build_object('rows',count(*),'sha256',encode(sha256(convert_to("
            f"COALESCE(string_agg({text},E'\\n' ORDER BY ({text}) COLLATE \"C\"),''),"
            f"'UTF8')),'hex')) FROM public.\"{name}\" t")
    return dict(server=info, tables=tables)


def verify_full_restore(source, restored):
    if (source['server']['pg_major'] != 17 or restored['server']['pg_major'] != 17
            or source['server']['system_identifier'] == restored['server']['system_identifier']
            or not source['server']['system_identifier'] or not restored['server']['system_identifier']
            or source['tables'] != restored['tables']):
        raise DeploymentError('Actual isolated PG17 restore differs from the source database')


class IsolatedRestore:
    def __init__(self, root, image, network, *, runner=None, memory_mib=None, health_checker=None):
        self.root, self.image, self.network = Path(root), image, network
        self.runner, self.memory_mib = runner or run, memory_mib
        self.health_checker = health_checker
        if memory_mib is not None and (type(memory_mib) is not int or memory_mib <= 0):
            raise DeploymentError('Invalid isolated restore memory limit')
        self.name = 'xiquan-operations-restore-' + uuid.uuid4().hex
        self.volume = self.name + '-data'
        self.password = secrets.token_urlsafe(48)
        self.started = False

    def start(self):
        env = self.root / (self.name + '.env')
        write_environment(env, dict(POSTGRES_USER='operations_restore',
            POSTGRES_DB='operations_restore', POSTGRES_PASSWORD=self.password))
        self.runner(['docker', 'volume', 'create', '--label', 'xiquan.operations.restore=' + self.name, self.volume])
        limits = [] if self.memory_mib is None else ['--memory', str(self.memory_mib) + 'm',
            '--memory-swap', str(self.memory_mib) + 'm', '--cpus', '1', '--pids-limit', '128']
        settings = [] if self.memory_mib is None else ['-c', 'shared_buffers=16MB', '-c', 'work_mem=4MB',
            '-c', 'maintenance_work_mem=64MB', '-c', 'max_connections=20', '-c', 'max_parallel_workers=0',
            '-c', 'max_parallel_maintenance_workers=0']
        self.runner(['docker', 'run', '-d', '--name', self.name, '--restart', 'no', *limits,
            '--label', 'xiquan.operations.restore=' + self.name,
            '--network', self.network, '--env-file', str(env),
            '--mount', 'type=volume,src=' + self.volume + ',dst=/var/lib/postgresql/data',
            '--health-cmd', 'pg_isready -U operations_restore -d operations_restore',
            '--health-interval', '2s', '--health-start-period', '20s', '--health-retries', '30', self.image, *settings])
        self.started = True
        if self.health_checker is None:
            wait_healthy(self.name, runner=self.runner)
        else:
            self.health_checker(self.name)

    def restore(self, dump):
        if not self.started: raise DeploymentError('Isolated restore container has not started')
        self.runner(['docker', 'exec', '-i', self.name, 'pg_restore', '--exit-on-error', '--no-owner', '--no-acl',
            '-U', 'operations_restore', '-d', 'operations_restore'], input_file=Path(dump))

    @property
    def database_url(self):
        return 'postgresql+psycopg://operations_restore:' + quote(self.password, safe='') + '@' + self.name + ':5432/operations_restore'

    def stop(self):
        if not self.started: return
        info = json.loads(self.runner(['docker', 'inspect', self.name], timeout=20))[0]
        if info['Config'].get('Labels', {}).get('xiquan.operations.restore') != self.name:
            raise DeploymentError('Restore container identity changed; refuse to stop another container')
        self.runner(['docker', 'stop', self.name], timeout=60)
        self.started = False
        # Container, volume, private evidence and env remain; no deletion/prune.
