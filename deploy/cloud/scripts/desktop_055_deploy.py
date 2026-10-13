"""Private evidence and exact checkpoints for additive wristband chip admission."""
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from operations_backup_verify import DeploymentError
from operations_deploy import json_read, json_write
from operations_preflight import no_links
from operations_preflight import digest_file, safe_relative, stage_bundle, protected_files, READ_ONLY_SQL
from operations_deploy import CLOUD, PROJECT, BACKUPS, MOUNT, require_single_api
from operations_backup_verify import IsolatedRestore, inspect_database, verify_full_restore, write_environment
from operations_offline_build import IMAGE_PROBE, require_dependencies, requirements_digest, expected_payload

TOOLS = ('desktop_055_deploy.py', 'desktop_055_guard.py', 'desktop_055_pgproof.py', 'stock_guard.py',
         'stock_deploy.py', 'operations_backup_verify.py', 'operations_preflight.py', 'operations_deploy.py',
         'operations_offline_build.py')
TARGETS = ['win10-x86', 'win10-x64', 'win11-x86', 'win11-x64']

OLD = '20261013_wristband_chip'
HEAD = '20261013_manual_inventory_excel'
PHASES = ('before', 'maintenance', 'rehearsal', 'after', 'after-backup', 'ready',
          'source-switch', 'paused-api', 'maintenance-release', 'normal-worker', 'cleanup', 'origin')
CLEANUP_PROBE = """import json, sys, time
from pathlib import Path
try:
    beat = json.loads(Path('/tmp/xiquan-receipt-cleanup-health.json').read_text())
    healthy = beat['ok'] is True and 0 <= time.time() - beat['checked_at'] <= 120
except Exception:
    healthy = False
sys.exit(0 if healthy else 1)"""


EXCEL_ROUTE = '''    # desktop055 bounded JSON/base64 workbook uploads only.
    location ~ ^/api/inventory/excel/(preview|apply)$ {
        client_max_body_size 15m;
        proxy_pass http://api:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90s;
    }

'''

def excel_upload_configuration(value):
    if EXCEL_ROUTE in value:
        require(value.count(EXCEL_ROUTE) == 1, 'Duplicate Excel upload route')
        return value
    require('/api/inventory/excel/' not in value, 'Unexpected existing Excel upload route')
    index = value.rfind('    location / {')
    require(index >= 0, 'Expected reviewed nginx upstream location missing')
    return value[:index] + EXCEL_ROUTE + value[index:]


def require(value, message):
    if not value:
        raise DeploymentError(message)


def resource_budget(available, disk, *, restore=False, maintenance=True, allocation_mib=0):
    # MemAvailable already accounts for running containers. These are upcoming
    # simultaneous allocations: one 256MiB maintenance process, optional restore.
    required = (256 if maintenance else 0) + 128 + (256 if restore else 0) + allocation_mib
    require(disk >= 6 * 1024**3, 'Need 6 GiB free backup disk; retain all evidence')
    require(available >= required * 1024**2, 'Insufficient current memory budget')
    return dict(available_memory_mib=available // 1024**2, required_memory_mib=required,
                maintenance_limit_mib=256, restore_limit_mib=256, reserve_mib=128,
                upcoming_service_mib=allocation_mib, backup_free_mib=disk // 1024**2)


def normalize_compose_limits(config):
    """Compose JSON uses decimal strings; Docker inspect uses integer bytes."""
    config = copy.deepcopy(config)
    for service in config['services'].values():
        for key in ('mem_limit', 'memswap_limit'):
            if key not in service:
                continue
            value = service[key]
            require((type(value) is int and value >= 0) or
                    (isinstance(value, str) and re.fullmatch(r'[0-9]+', value) is not None),
                    'Invalid Compose memory byte count; no coercion or limit bypass')
            service[key] = int(value)
    return config


def validate_merged_compose(old, new):
    """Inputs are docker compose's merged JSON, with staged mounts normalized."""
    old, new = normalize_compose_limits(old), normalize_compose_limits(new)
    require(all(new['services']['api'].get(key) == 512 * 1024**2 for key in ('mem_limit', 'memswap_limit')),
            'API must have the reviewed 512 MiB limit')
    for config in (old, new):
        api = config['services']['api']
        env = api['environment']
        require('MAINTENANCE_DATABASE_URL' not in env and env['DATABASE_URL'] == env['RUNTIME_DATABASE_URL'],
                'Normal API owner credentials forbidden')
    worker = new['services']['receipt-cleanup']
    require(worker.get('mem_limit') == 256 * 1024**2 and worker.get('memswap_limit') == 256 * 1024**2,
            'Cleanup must have a 256 MiB limit')
    require(not worker.get('ports') and not worker.get('expose') and set(worker['networks']) == {'backend'} and
            worker['entrypoint'] == ['python', '-m', 'app.receipt_cleanup_worker'] and
            worker['environment']['DATABASE_URL'] == worker['environment']['MAINTENANCE_DATABASE_URL'],
            'Cleanup private owner contract differs')
    require(worker['healthcheck'] == dict(test=['CMD', 'python', '-c', CLEANUP_PROBE], interval='10s',
            timeout='3s', start_period='15s', retries=6), 'Cleanup heartbeat contract differs')
    for config in (old, new):
        for key in ('mem_limit', 'memswap_limit'):
            config['services']['api'].pop(key, None)
        for key in ('mem_limit', 'memswap_limit', 'healthcheck'):
            config['services']['receipt-cleanup'].pop(key, None)
    require(old == new, 'Merged Compose changed beyond reviewed API/cleanup limits/probe')


class OperationDeadline:
    """One finite cutover deadline; individual commands cannot outlive it."""
    def __init__(self, seconds=14400):
        self.expires = time.monotonic() + seconds

    def remaining(self):
        return max(0, self.expires - time.monotonic())


class PrivateRunner:
    """Never expose argv/stdout/stderr; keep original diagnostic bytes privately."""
    def __init__(self, root, phase, *, deadline=None):
        self.root, self.phase = no_links(root), phase
        self.deadline = deadline

    def __call__(self, argv, *, input_file=None, timeout=1800):
        started = time.time()
        category, code, stdout, stderr = None, None, '', ''
        if self.deadline is not None:
            timeout = min(timeout, self.deadline.remaining())
            if timeout <= 0:
                path = self.root / ('command-' + uuid.uuid4().hex + '.json')
                json_write(path, dict(phase=self.phase(), category='deadline', exit_code=None,
                                     timeout_seconds=0))
                raise DeploymentError(f'phase={self.phase()} category=deadline evidence={path}')
        try:
            with input_file.open('rb') if input_file else nullcontext(None) as stream:
                result = subprocess.run(argv, stdin=stream, capture_output=True, text=True, timeout=timeout)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
            if code:
                category = 'sigkill137' if code in (137, -9) else 'exit'
        except subprocess.TimeoutExpired as error:
            category = 'timeout'
            stdout, stderr = error.stdout or '', error.stderr or ''
        except OSError as error:
            category, stderr = 'spawn', repr(error)
        if category:
            path = self.root / ('command-' + uuid.uuid4().hex + '.json')
            decode = lambda v: v.decode('utf-8', 'replace') if isinstance(v, bytes) else v
            json_write(path, dict(phase=self.phase(), category=category, exit_code=code,
                command=argv, started_at=started, timeout_seconds=timeout,
                stdout=decode(stdout), stderr=decode(stderr)))
            raise DeploymentError(f'phase={self.phase()} category={category} exit={code} evidence={path}')
        return stdout.strip()

    def healthy(self, name, timeout=180):
        deadline = time.monotonic() + timeout
        while True:
            info = json.loads(self(['docker', 'inspect', name], timeout=20))[0]
            state = info['State']
            if state.get('Running') and state.get('Health', {}).get('Status') == 'healthy':
                return info
            if state.get('OOMKilled') or not state.get('Running') or state.get('Health', {}).get('Status') == 'unhealthy' or time.monotonic() >= deadline:
                category = ('oom' if state.get('OOMKilled') else 'sigkill137' if state.get('ExitCode') == 137
                            else 'exit' if not state.get('Running')
                            else 'healthcheck' if state.get('Health', {}).get('Status') == 'unhealthy' else 'timeout')
                path = self.root / ('health-' + uuid.uuid4().hex + '.json')
                json_write(path, dict(phase=self.phase(), category=category, container=info))
                raise DeploymentError(f'phase={self.phase()} category={category} evidence={path}')
            time.sleep(2)


class Checkpoints:
    """Receipts are immutable and bound to source, pinned image and owned job."""
    def __init__(self, root, identity):
        self.root, self.identity = no_links(root), identity

    def validate(self):
        done, missing = [], False
        for phase in PHASES:
            path = self.root / (phase + '.json')
            if not path.exists():
                missing = True
                continue
            require(not missing, 'Checkpoint receipt has a hole')
            record = json_read(path)
            require(record.get('phase') == phase and all(record.get(k) == v for k, v in self.identity.items()),
                    'Checkpoint identity differs')
            require(isinstance(record.get('result'), dict), 'Checkpoint result missing')
            done.append(phase)
        return done

    def classify(self, schema, maintenance, owner):
        done = self.validate()
        migrated = 'after' in done
        require(schema == (HEAD if migrated else OLD), 'Unclassified migration result; do not replay DDL')
        if maintenance:
            require(owner == self.identity['job'], 'Foreign maintenance cannot be resumed')
            require('maintenance-release' not in done, 'Unexpected maintenance after release')
        elif 'maintenance' in done and 'maintenance-release' not in done:
            require('paused-api' in done, 'Owned maintenance disappeared before paused API')
            return 'release-receipt-required'
        return PHASES[len(done)] if len(done) < len(PHASES) else 'completed'

    def run(self, operation):
        done = self.validate()
        require(not (self.root / 'completed.json').exists(), 'Already completed')
        for phase in PHASES[len(done):]:
            result = operation(phase)
            require(isinstance(result, dict), 'Phase must return verified evidence')
            json_write(self.root / (phase + '.json'), dict(self.identity, phase=phase, result=result))
        origin = json_read(self.root / 'origin.json')['result']
        json_write(self.root / 'completed.json', dict(self.identity, phase='completed', origin=origin))


def verify_source(source):
    manifest = json_read(source / 'source-manifest.json')
    require(manifest.get('asset_source_commit') == manifest['source_commit'] and
            manifest.get('schema_head') == HEAD and manifest.get('desktop_version') == '0.5.5' and
            manifest.get('android_version') == '1.2.12' and manifest.get('android_version_code') == 19 and
            manifest.get('targets') == TARGETS, 'Exact 0.5.5 source contract required')
    records = {r['file']: r for r in manifest['files']}
    require(len(records) == len(manifest['files']), 'Duplicate source record')
    for row in manifest['files']:
        safe_relative(row['file'])
        file = no_links(source / row['file'])
        require(file.stat().st_size == row['size'] and digest_file(file) == row['sha256'], 'Source bytes differ')
    for name in TOOLS:
        relative = 'deploy/cloud/scripts/' + name
        require(relative in records and digest_file(source / relative) == digest_file(Path(__file__).parent / name),
                'Transport differs from committed source')
    for name in ('server/app/member_cards.py', 'server/app/member_payment.py', 'server/app/receipt_cleanup_worker.py',
                 'server/app/wristband_reader_service.py', 'server/app/api/wristband_reader.py',
                 'server/app/inventory_xlsx.py', 'server/app/inventory_excel_service.py', 'server/app/api/inventory_excel.py',
                 'server/migrations/versions/' + HEAD + '.py', 'deploy/cloud/scripts/runtime-role.sql',
                 'deploy/cloud/scripts/reset-role.sql', 'deploy/cloud/scripts/backup-role.sql'):
        require(name in records, 'Required reviewed source missing')
    client = json_read(source / 'client/package.json')
    mobile = json_read(source / 'mobile/version.json')
    require(client['version'] == '0.5.5' and client['build']['appId'] == 'com.xiquan.bathhouse' and
            mobile['version'] == '1.2.12' and mobile['versionCode'] == 19, 'Application identity/version differs')
    return manifest


def cloud_state(runner):
    # Add owner identity to the existing reviewed read-only state query.
    sql = READ_ONLY_SQL.replace("'maintenance',maintenance,", "'maintenance',maintenance,'maintenance_reset_id',maintenance_reset_id,")
    shell = 'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"'
    return json.loads(runner(['docker', 'exec', 'xiquan-postgres-1', 'sh', '-eu', '-c', shell, 'sh', sql], timeout=60))


def fresh_state(runner):
    state = cloud_state(runner)
    require(state['pg_major'] == 17 and state['schema_revision'] == OLD and not state['pending_resets'] and
            not state['business_state']['maintenance'] and not state['business_state']['maintenance_reset_id'] and
            state['active_policy']['policy_version'] == state['business_state']['policy_version'],
            'Require PG17 exact predecessor, matching policy, no maintenance or reset')
    return state


def private_directory(path):
    path = no_links(path)
    require(path.is_dir() and path.stat().st_uid == 0 and not path.stat().st_mode & 0o077,
            'Private root-owned directory required')
    return path


def require_owned_command(info, owner, image):
    require(info['Image'] == image and info['Config'].get('Labels', {}).get('xiquan.desktop055.job') == owner,
            'Refuse to stop an unowned command container')


def verify_released_snapshot(before, after, owner):
    before, after = copy.deepcopy(before), copy.deepcopy(after)
    require(before['schema_revision'] == after['schema_revision'] == HEAD and
            before['control_state']['maintenance'] is True and before['control_state']['maintenance_reset_id'] == owner,
            'Release baseline is not owned')
    before['control_state'].update(maintenance=False, maintenance_reset_id=None)
    for value in (before, after):
        require(value['old_row_hashes']['business_state']['rows'] == 1, 'Control state cardinality changed')
        value['old_row_hashes'].pop('business_state')
    require(before == after, 'Unclassified changes after maintenance release')


class Desktop055:
    """Own all version decisions; share only byte copy, backup and image probes."""
    def __init__(self, stage, job=None):
        require(re.fullmatch('/opt/xiquan-releases/desktop055-stage-[0-9a-f]{32}', stage or ''), 'Invalid exact stage')
        self.stage = private_directory(stage)
        self.source = self.stage / 'xiquan'
        self.manifest = verify_source(self.source)
        self.report = json_read(self.stage / 'desktop-stage.json')
        require(self.report['source_commit'] == self.manifest['source_commit'], 'Stage commit differs')
        require(not job or re.fullmatch('/opt/xiquan-backups/desktop055-cutover-[0-9a-f]{32}', job), 'Invalid exact job')
        self.job = private_directory(job) if job else None
        self.context = json_read(self.job / 'context.json') if job else {}
        self.last_phase, self.restores = 'preflight', []
        self.run = PrivateRunner(self.job or self.stage, lambda: self.last_phase)
        self.resolve_environment()

    def config(self, file):
        return normalize_compose_limits(json.loads(self.run(['docker', 'compose', '--env-file', str(CLOUD / '.env'), '-p', 'xiquan',
            '-f', str(file), '--profile', 'maintenance', 'config', '--format', 'json'])))

    def resolve_environment(self):
        from urllib.parse import urlsplit
        config = self.config(self.source / 'deploy/cloud/docker-compose.prod.yml')
        normal = {k: str(v) for k, v in config['services']['api']['environment'].items() if v is not None}
        owner = {k: str(v) for k, v in config['services']['maintenance']['environment'].items() if v is not None}
        require('MAINTENANCE_DATABASE_URL' not in normal and normal['DATABASE_URL'] == normal['RUNTIME_DATABASE_URL'],
                'API must use runtime identity only')
        urls = [urlsplit(v) for v in (owner['DATABASE_URL'], normal['DATABASE_URL'], normal['RESET_DATABASE_URL'], normal['RESET_BACKUP_DATABASE_URL'])]
        require(all(u.scheme == 'postgresql+psycopg' and u.hostname and u.username and u.password and u.path.strip('/') for u in urls)
                and len({(u.hostname, u.port or 5432, u.path) for u in urls}) == 1 and len({u.username for u in urls}) == 4
                and [u.username for u in urls[1:]] == ['xiquan_app', 'xiquan_reset', 'xiquan_backup'], 'Four distinct existing database roles required')
        owner.update(RESET_PRIVATE_DIR=MOUNT, MAINTENANCE_PROCESS='1', RESET_WORKER_ENABLED='0', SMS_ENABLED='0',
                     RUNTIME_DATABASE_URL=normal['DATABASE_URL'], RESET_DATABASE_URL=normal['RESET_DATABASE_URL'])
        self.env, self.normal_env = owner, normal

    def budget(self, *, restore=False, maintenance=True, allocation_mib=0):
        match = re.search(r'^MemAvailable:\s+(\d+)\s+kB', Path('/proc/meminfo').read_text(), re.M)
        require(match is not None, 'Cannot measure current memory')
        evidence = resource_budget(int(match[1]) * 1024, shutil.disk_usage(BACKUPS).free,
                                   restore=restore, maintenance=maintenance, allocation_mib=allocation_mib)
        if self.job: json_write(self.job / ('resources-' + uuid.uuid4().hex + '.json'), dict(phase=self.last_phase, **evidence))
        return evidence

    def phase(self, name):
        self.last_phase = name
        self.budget(maintenance=False)
        if self.job: json_write(self.job / ('phase-' + uuid.uuid4().hex + '.json'), dict(phase=name))
        print('DESKTOP055_PHASE=' + name, flush=True)

    def protected(self):
        current = protected_files(CLOUD)
        expected = copy.deepcopy(self.report['protected'])
        receipt = self.job / 'nginx-excel-switch.json' if self.job else None
        if receipt and receipt.exists():
            switch = json_read(receipt)
            require(switch['original'] == expected['nginx/active.conf'], 'Original nginx protection differs')
            actual = current['nginx/active.conf']
            if actual != expected['nginx/active.conf']:
                require({key:actual[key] for key in ('sha256','size')} == switch['after'], 'Reviewed Excel route differs')
                expected['nginx/active.conf'] = actual
        require(current == expected, 'Protected release references changed')

    def compose(self, *args, override=None):
        argv = ['docker', 'compose', '--env-file', str(CLOUD / '.env'), '-p', 'xiquan', '-f', str(CLOUD / 'docker-compose.prod.yml')]
        if override: argv += ['-f', str(override)]
        return self.run(argv + list(args))

    def validate_compose(self):
        configs = [self.config(file) for file in (CLOUD / 'docker-compose.prod.yml', self.source / 'deploy/cloud/docker-compose.prod.yml')]
        for config in configs:
            for service in config['services'].values():
                build = service.get('build')
                if isinstance(build, dict) and 'context' in build:
                    try: relative = Path(build['context']).relative_to(self.source)
                    except ValueError: pass
                    else: build['context'] = str(PROJECT / relative)
                for mount in service.get('volumes', []):
                    try: relative = Path(mount.get('source', '')).relative_to(self.source)
                    except ValueError: continue
                    mount['source'] = str(PROJECT / relative)
        validate_merged_compose(*configs)
        json_write((self.job or self.stage) / ('merged-compose-' + uuid.uuid4().hex + '.json'), dict(before=configs[0], after=configs[1]))

    def image_probe(self, image):
        self.budget()
        proof = json.loads(self.run(['docker', 'run', '--rm', '--memory', '256m', '--memory-swap', '256m',
            '--network', 'none', '--entrypoint', 'python', image, '-c', IMAGE_PROBE]))
        require_dependencies(proof, requirements_digest((self.source / 'server/requirements.txt').read_bytes()))
        return proof

    def build(self, old_image):
        self.phase('offline-build')
        self.image_probe(old_image)
        config = json.loads(self.run(['docker', 'image', 'inspect', old_image]))[0]['Config']
        require(config.get('WorkingDir') == '/app' and config.get('User') == 'xiquan' and
                config.get('Entrypoint') == ['/app/docker-entrypoint.sh'] and config.get('Cmd') == ['python', 'run.py'],
                'Existing image startup differs')
        base = 'xiquan-api:desktop055-base-' + self.context['owner']
        self.run(['docker', 'tag', old_image, base])
        file = self.job / 'Dockerfile'
        file.write_text('FROM ' + base + '\nUSER root\nRUN test -d /app/app && test -d /app/migrations && rm -rf /app/app /app/migrations\n'
            'COPY --chown=xiquan:xiquan app /app/app\nCOPY --chown=xiquan:xiquan migrations /app/migrations\n'
            'COPY --chown=xiquan:xiquan run.py docker-entrypoint.sh /app/\n'
            "RUN sed -i 's/\\r$//' /app/docker-entrypoint.sh && chmod 0755 /app/docker-entrypoint.sh\nUSER xiquan\n", encoding='utf-8')
        file.chmod(0o600)
        tag = 'xiquan-api:desktop055-' + self.context['owner']
        self.run(['docker', 'build', '--pull=false', '--network=none', '--memory', '256m', '-f', str(file), '-t', tag, str(self.source / 'server')])
        image = json.loads(self.run(['docker', 'image', 'inspect', tag]))[0]['Id']
        require(self.image_probe(image)['payload'] == expected_payload(self.source / 'server'), 'Pinned image source differs')
        self.context['image_id'] = image

    def command(self, args, environment=None, network=None, extra_network=None):
        self.budget()
        name = 'xiquan-desktop055-command-' + uuid.uuid4().hex
        argv = ['docker', 'run', '--name', name, '--user', '0:0', '--memory', '256m', '--memory-swap', '256m',
            '--label', 'xiquan.desktop055.job=' + self.context['owner'],
            '--cpus', '1', '--pids-limit', '128', '--env', 'PYTHONPATH=/app:/', '--network', network or self.context['network']]
        if extra_network: argv += ['--network', extra_network]
        argv += ['--env-file', str(environment or self.job / 'maintenance.env'), '--mount', 'type=bind,src=' + str(self.job) + ',dst=' + MOUNT]
        for filename in ('desktop_055_guard.py', 'desktop_055_pgproof.py', 'stock_guard.py'):
            argv += ['--mount', 'type=bind,src=' + str(self.source / 'deploy/cloud/scripts' / filename) + ',dst=/' + filename + ',readonly']
        argv += ['--entrypoint', 'python', self.context['image_id'], *args]
        try:
            return self.run(argv, timeout=1800)
        except Exception:
            # Keep stopped container and raw State so OOM is distinguishable
            # from a plain SIGKILL exit. No remove/prune or automatic restart.
            try:
                info = json.loads(self.run(['docker', 'inspect', name], timeout=20))[0]
                json_write(self.job / ('container-' + uuid.uuid4().hex + '.json'), dict(phase=self.last_phase, container=info))
                if info['State'].get('OOMKilled'): print('DESKTOP055_CATEGORY=oom', flush=True)
                require_owned_command(info, self.context['owner'], self.context['image_id'])
                if info['State'].get('Running'):
                    self.run(['docker', 'stop', '--time', '10', name], timeout=30)
            except Exception: pass
            raise

    def guard(self, mode, baseline=None, environment=None, network=None):
        argv = ['/desktop_055_guard.py', mode, '--job', self.context['owner']]
        if baseline is not None:
            path = self.job / ('baseline-' + uuid.uuid4().hex + '.json')
            json_write(path, baseline)
            argv += ['--baseline', MOUNT + '/' + path.relative_to(self.job).as_posix()]
        return json.loads(self.command(argv, environment, network))

    def restore(self, dump):
        require(not any(r.started for r in self.restores), 'Stop prior isolated restore first')
        self.budget(restore=True)
        restore = IsolatedRestore(self.job, self.context['postgres_image'], self.context['isolated_network'],
                                  runner=self.run, memory_mib=256, health_checker=self.run.healthy)
        self.restores.append(restore)
        restore.start(); restore.restore(dump)
        return restore

    def backup(self, name):
        folder = self.job / (name + '-backup-data')
        if folder.exists() and not (folder / 'receipt.json').exists():
            folder.rename(self.job / (folder.name + '-retained-' + uuid.uuid4().hex))
        if not folder.exists():
            folder.mkdir(mode=0o700)
            self.backup_command(['-m', 'flask', '--app', 'run.py', 'operations-backup', 'create', '--output', MOUNT + '/' + folder.name])
        dump = folder / 'database.backup'
        clone = self.restore(dump)
        verify_full_restore(inspect_database('xiquan-postgres-1', runner=self.run), inspect_database(clone.name, runner=self.run))
        if not (folder / 'receipt.json').exists():
            env = self.job / ('restore-' + uuid.uuid4().hex + '.env')
            write_environment(env, dict(self.env, XIQUAN_RESTORE_DATABASE_URL=clone.database_url))
            self.backup_command(['-m', 'flask', '--app', 'run.py', 'operations-backup', 'verify-restored', '--database-url-env',
                          'XIQUAN_RESTORE_DATABASE_URL', '--receipt', MOUNT + '/' + folder.name + '/candidate.json'],
                         environment=env, extra_network=self.context['isolated_network'])
        receipt = json_read(folder / 'receipt.json')
        require(receipt['restore']['status'] == 'verified' and digest_file(dump) == receipt['dump_sha256'], 'Backup receipt mismatch')
        clone.stop()
        return dict(folder=folder.name, dump_sha256=receipt['dump_sha256'], restore='verified')

    def backup_command(self, args, **kwargs):
        folder = no_links(self.job / 'backup-diagnostics')
        folder.mkdir(mode=0o700, exist_ok=True)
        private_directory(folder)
        path = folder / ('backup-diagnostic-' + uuid.uuid4().hex + '.json')
        try:
            return self.command([*args, '--private-evidence', MOUNT + '/' + path.relative_to(self.job).as_posix()], **kwargs)
        except Exception:
            if path.exists():
                evidence = json_read(path)
                category = evidence.get('category')
                require(category in ('timeout', 'sigkill137', 'exit', 'verification'), 'Invalid inner failure category')
                code = evidence.get('exit_code')
                require(code is None or type(code) is int, 'Invalid inner failure exit')
                raise DeploymentError(f'phase={self.last_phase} category={category} exit={code} evidence={path}') from None
            raise

    def rehearsal(self):
        import secrets
        from urllib.parse import quote
        clone = self.restore(self.job / self.result('before')['backup']['folder'] / 'database.backup')
        suffix = uuid.uuid4().hex
        passwords = {r: secrets.token_urlsafe(48) for r in ('xiquan_app', 'xiquan_reset', 'xiquan_backup')}
        sql = self.job / ('clone-logins-' + suffix + '.sql')
        sql.write_text(''.join("CREATE ROLE " + r + " LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '" + p + "';\n" for r, p in passwords.items()), encoding='utf-8')
        sql.chmod(0o600)
        def psql(file):
            self.run(['docker', 'exec', '-i', clone.name, 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-U', 'operations_restore', '-d', 'operations_restore'], input_file=file)
        psql(sql)
        env = self.job / ('clone-' + suffix + '.env')
        url = lambda r: 'postgresql+psycopg://' + r + ':' + quote(passwords[r], safe='') + '@' + clone.name + ':5432/operations_restore'
        write_environment(env, dict(self.env, DATABASE_URL=clone.database_url, MAINTENANCE_DATABASE_URL=clone.database_url,
            RUNTIME_DATABASE_URL=url('xiquan_app'), RESET_DATABASE_URL=url('xiquan_reset'), RESET_BACKUP_DATABASE_URL=url('xiquan_backup')))
        before = self.guard('inspect', environment=env, network=self.context['isolated_network'])
        claimed = self.guard('claim', before, env, self.context['isolated_network'])
        after = self.guard('migrate', claimed, env, self.context['isolated_network'])
        json_write(self.job / ('clone-preserved-' + suffix + '.json'), dict(before=claimed, after=after))
        for name in ('runtime-role.sql', 'reset-role.sql', 'backup-role.sql'): psql(self.source / 'deploy/cloud/scripts' / name)
        login = self.job / ('clone-enable-' + suffix + '.sql')
        login.write_text(''.join('ALTER ROLE ' + r + ' LOGIN;\n' for r in passwords), encoding='utf-8'); login.chmod(0o600); psql(login)
        proof = self.guard('proof', environment=env, network=self.context['isolated_network'])
        require(all(proof.get(k) is True for k in ('pg17', 'isolated', 'uid_unique', 'scan_concurrency', 'replay_exact',
                'login_isolation', 'period_guard', 'maintenance_barrier', 'backup_readable',
                'manual_stock_unchanged', 'excel25_confirmation', 'excel_atomic_replay', 'cost_password', 'pending_units')) and proof['runtime_roles']['verified'] and
                all(k in proof for k in ('compatibility',)),
                'Incomplete isolated PostgreSQL proof')
        clone.stop()
        return proof

    def result(self, phase):
        return json_read(self.job / (phase + '.json'))['result']

    def install(self):
        from stock_deploy import Stock
        def copy_record(row, target, mode):
            target = no_links(target)
            temporary = no_links(target.with_name(target.name + '.stock-' + self.context['owner']))
            if temporary.exists():
                temporary.rename(self.job / ('retained-copy-' + uuid.uuid4().hex))
            Stock.copy(self, row, target, mode)
        for row in self.manifest['files']:
            if row['file'].startswith('server/') or row['file'] in {'deploy/cloud/scripts/' + n for n in (*TOOLS, 'runtime-role.sql')}:
                copy_record(row, PROJECT / row['file'], 0o644)
        for area, target in (('client/dist/', CLOUD / 'web'), ('mobile/dist/', CLOUD / 'mobile')):
            for row in sorted(self.manifest['files'], key=lambda r: r['file'].endswith('/index.html')):
                if row['file'].startswith(area):
                    relative = row['file'][len(area):]
                    require(not relative.startswith('downloads/') and relative != 'download-config.json', 'Protected public path')
                    copy_record(row, target / relative, 0o644)
        row = next(r for r in self.manifest['files'] if r['file'] == 'deploy/cloud/docker-compose.prod.yml')
        copy_record(row, CLOUD / 'docker-compose.prod.yml', 0o600)
        config = no_links(CLOUD / 'nginx/active.conf')
        text = config.read_text(encoding='utf-8')
        updated = excel_upload_configuration(text)
        if updated != text:
            shutil.copy2(config, self.job / 'nginx-before-excel.conf')
            json_write(self.job / 'nginx-excel-switch.json', dict(original=self.report['protected']['nginx/active.conf'],
                after=dict(sha256=hashlib.sha256(updated.encode('utf-8')).hexdigest(),size=len(updated.encode('utf-8')))))
            temporary = no_links(config.with_name('active.conf.desktop055-' + self.context['owner']))
            temporary.write_text(updated, encoding='utf-8'); temporary.chmod(0o644); os.replace(temporary, config)
        self.run(['docker', 'tag', self.context['image_id'], 'xiquan-api:owner-reset'])
        return dict(compose_sha256=row['sha256'],nginx_sha256=digest_file(config))

    def verify_api(self, worker):
        require(cloud_state(self.run)['schema_revision'] == HEAD, 'Pinned API requires exact 0.5.5 schema')
        info = self.run.healthy('xiquan-api-1')
        require(all(info['HostConfig'].get(key) == 512 * 1024**2 for key in ('Memory', 'MemorySwap')), 'API memory limit differs')
        env = dict(v.split('=', 1) for v in info['Config']['Env'] if '=' in v)
        require(info['Image'] == self.context['image_id'] and env.get('RESET_WORKER_ENABLED') == worker and
            'MAINTENANCE_DATABASE_URL' not in env and all(env.get(k, '') == self.normal_env.get(k, '') for k in
             ('DATABASE_URL', 'SECRET_KEY', 'JWT_SECRET_KEY', 'AUDIT_HMAC_KEY', 'REGISTRATION_TOKEN_SECRET')) and
            all(env.get(k, '0') == '0' for k in ('AUTO_CREATE_DB', 'RUN_MIGRATIONS', 'SEED_DEFAULTS')), 'Pinned API runtime differs')
        require_single_api(self.run(['docker', 'ps', '--filter', 'label=com.docker.compose.project=xiquan',
            '--filter', 'label=com.docker.compose.service=api', '--format', '{{json .}}']))
        self.run(['docker', 'exec', 'xiquan-nginx-1', 'nginx', '-t'])
        self.run(['docker', 'exec', 'xiquan-nginx-1', 'nginx', '-s', 'reload'])
        return dict(image_id=info['Image'], reset_worker=worker, container_id=info['Id'])

    def startup_budget(self, service):
        limit = {'api': 512, 'receipt-cleanup': 256}[service]
        config = self.config(CLOUD / 'docker-compose.prod.yml')['services'][service]
        require(all(config.get(key) == limit * 1024**2 for key in ('mem_limit', 'memswap_limit')),
                'Startup configured memory limit differs')
        existing = json.loads(self.run(['docker', 'inspect', 'xiquan-' + service + '-1'], timeout=20))[0]
        # MemAvailable already includes existing allocations; never credit an old
        # container's RSS/limit before Compose has actually stopped it.
        json_write(self.job / ('startup-overlap-' + uuid.uuid4().hex + '.json'),
                   dict(phase=self.last_phase, service=service, existing=existing, upcoming_mib=limit))
        return self.budget(maintenance=False, allocation_mib=limit)

    def start_api(self, worker):
        override = self.job / ('override-' + uuid.uuid4().hex + '.json')
        json_write(override, dict(services={'api': dict(image=self.context['image_id'], environment=dict(RESET_WORKER_ENABLED=worker)),
                                          'receipt-cleanup': dict(image=self.context['image_id'])}))
        self.startup_budget('api')
        self.compose('up', '-d', '--no-deps', '--no-build', 'api', override=override)
        return self.verify_api(worker)

    def cleanup(self):
        override = self.job / ('cleanup-' + uuid.uuid4().hex + '.json')
        json_write(override, dict(services={'receipt-cleanup': dict(image=self.context['image_id'])}))
        self.startup_budget('receipt-cleanup')
        self.compose('up', '-d', '--no-deps', '--no-build', 'receipt-cleanup', override=override)
        info = self.run.healthy('xiquan-receipt-cleanup-1')
        require(info['Image'] == self.context['image_id'] and
                all(info['HostConfig'].get(key) == 256 * 1024**2 for key in ('Memory', 'MemorySwap')), 'Cleanup image/limit differs')
        require(not any(m.get('Destination') == '/app/app/receipt_cleanup_worker.py' for m in info.get('Mounts', [])),
                'New cleanup worker must use the reviewed image, not a historical single-file patch')
        first, deadline = None, time.monotonic() + 150
        while time.monotonic() < deadline:
            beat = json.loads(self.run(['docker', 'exec', 'xiquan-receipt-cleanup-1', 'python', '-c',
                "from pathlib import Path;print(Path('/tmp/xiquan-receipt-cleanup-health.json').read_text())"]))
            require(beat['ok'] is True and 0 <= time.time() - beat['checked_at'] <= 120, 'Cleanup heartbeat invalid')
            if first is not None and beat['checked_at'] > first:
                return dict(image_id=info['Image'], checked_at=[first, beat['checked_at']])
            first = beat['checked_at']
            time.sleep(5)
        raise DeploymentError('Cleanup second heartbeat timeout')

    def origin(self):
        proof = {}
        records = [(r['file'], ('app/' if r['file'].startswith('client/') else 'mobile/') + r['file'].split('/dist/', 1)[1], r['sha256'])
                   for r in self.manifest['files'] if r['file'].startswith(('client/dist/', 'mobile/dist/'))]
        for origin in (True, False):
            for label, route, digest in [('health', 'api/health', None), *records]:
                require(re.fullmatch('[A-Za-z0-9_./-]+', route), 'Unsafe public route')
                output = self.job / ('http-' + uuid.uuid4().hex)
                argv = ['curl', '--http1.1', '--fail', '--silent', '--show-error', '--max-time', '30', '--output', str(output), '--write-out', '%{http_code}']
                if origin: argv += ['--resolve', 'api.pqxqxy.xyz:443:127.0.0.1']
                status = self.run(argv + ['https://api.pqxqxy.xyz/' + route], timeout=40)
                require(status == '200', 'HTTP status differs from 200')
                output.chmod(0o600)
                actual = digest_file(output)
                if digest: require(actual == digest, 'Exact public bytes differ')
                else:
                    health = json_read(output)
                    require(health.get('success') is True and health.get('data', {}).get('database') == 'ok', 'HTTP health failed')
                proof[('origin:' if origin else 'public:') + label] = actual
        self.verify_api('1'); self.protected()
        return dict(hashes=proof, compatibility_scope=self.result('rehearsal')['compatibility']['scope'])

    def perform(self, phase):
        self.phase(phase)
        self.protected()
        require(digest_file(CLOUD / '.env') == self.context['env_sha256'], 'Private configuration changed')
        if phase == 'before':
            fresh_state(self.run)
            self.compose('stop', 'api', 'receipt-cleanup')
            snapshot = self.guard('inspect')
            backup = self.backup('before')
            require(self.guard('inspect') == snapshot, 'Pre-maintenance business data changed')
            return dict(snapshot=snapshot, backup=backup)
        if phase == 'maintenance': return self.guard('claim', self.result('before')['snapshot'])
        if phase == 'rehearsal': return self.rehearsal()
        if phase == 'after': return self.guard('migrate', self.result('maintenance'))
        if phase == 'after-backup':
            require(self.guard('inspect') == self.result('after'), 'Post-migration snapshot changed')
            return self.backup('after')
        if phase == 'ready':
            require(self.guard('inspect') == self.result('after'), 'Ready snapshot changed')
            return dict(backup=self.result('after-backup'), image_id=self.context['image_id'])
        if phase == 'source-switch': return self.install()
        if phase == 'paused-api': return self.start_api('0')
        if phase == 'maintenance-release': return self.guard('release', self.result('after'))
        if phase == 'normal-worker': return self.start_api('1')
        if phase == 'cleanup': return self.cleanup()
        if phase == 'origin': return self.origin()
        raise DeploymentError('Unknown phase')

    def identity(self):
        return dict(job=self.context['owner'], source_commit=self.report['source_commit'], source_sha256=self.report['bundle_sha256'],
                    target_schema=HEAD, image_id=self.context['image_id'])

    def deploy(self):
        self.protected(); fresh_state(self.run); self.validate_compose()
        info = [self.run.healthy(n) for n in ('xiquan-api-1', 'xiquan-postgres-1')]
        env = dict(v.split('=', 1) for v in info[0]['Config']['Env'] if '=' in v)
        require(all(env.get(k, '') == self.normal_env.get(k, '') for k in ('DATABASE_URL', 'SECRET_KEY', 'JWT_SECRET_KEY', 'AUDIT_HMAC_KEY', 'REGISTRATION_TOKEN_SECRET')),
                'Existing identity differs')
        networks = [n for n in set(info[0]['NetworkSettings']['Networks']) & set(info[1]['NetworkSettings']['Networks'])
                    if json.loads(self.run(['docker', 'network', 'inspect', n]))[0]['Internal']]
        require(len(networks) == 1, 'One private network required')
        owner = str(uuid.uuid4())
        self.job = no_links(BACKUPS / ('desktop055-cutover-' + owner.replace('-', ''))); self.job.mkdir(mode=0o700)
        self.run = PrivateRunner(self.job, lambda: self.last_phase, deadline=OperationDeadline())
        print('PRIVATE_DESKTOP_JOB=' + str(self.job), flush=True)
        self.context = dict(owner=owner, stage=str(self.stage), source_commit=self.report['source_commit'],
            source_sha256=self.report['bundle_sha256'], network=networks[0], isolated_network='xiquan-desktop055-' + owner,
            postgres_image=info[1]['Image'], env_sha256=digest_file(CLOUD / '.env'),
            tools={n: digest_file(Path(__file__).parent / n) for n in TOOLS})
        self.build(info[0]['Image'])
        json_write(self.job / 'context.json', self.context)
        write_environment(self.job / 'maintenance.env', self.env)
        self.run(['docker', 'network', 'create', '--internal', self.context['isolated_network']])
        Checkpoints(self.job, self.identity()).run(self.perform)

    def resume(self):
        require(self.job is not None, 'Exact job required')
        self.run.deadline = OperationDeadline()
        self.phase('resume-classify')
        require(self.context['stage'] == str(self.stage) and self.context['source_commit'] == self.report['source_commit'] and
                self.context['source_sha256'] == self.report['bundle_sha256'] and
                self.context['tools'] == {n: digest_file(Path(__file__).parent / n) for n in TOOLS}, 'Recovery identity changed')
        require(self.image_probe(self.context['image_id'])['payload'] == expected_payload(self.source / 'server'), 'Pinned image differs')
        state = cloud_state(self.run)
        running = self.run(['docker', 'ps', '--filter', 'label=xiquan.desktop055.job=' + self.context['owner'], '--format', '{{.ID}}'])
        require(not running, 'An owned maintenance command is still running; retain evidence')
        require(not state['pending_resets'], 'Pending reset during recovery')
        checkpoints = Checkpoints(self.job, self.identity())
        classified = checkpoints.classify(state['schema_revision'], state['business_state']['maintenance'], state['business_state']['maintenance_reset_id'])
        if classified == 'release-receipt-required':
            self.verify_api('0')
            verify_released_snapshot(self.result('after'), self.guard('inspect'), self.context['owner'])
            json_write(self.job / 'maintenance-release.json', dict(self.identity(), phase='maintenance-release',
                result=dict(released=True, owner=self.context['owner'], schema=HEAD, recovered_from_exact_snapshot=True)))
        if 'maintenance' in checkpoints.validate() and 'maintenance-release' not in checkpoints.validate():
            expected = self.result('after') if (self.job / 'after.json').exists() else self.result('maintenance')
            require(self.guard('inspect') == expected, 'Owned snapshot changed')
        if (self.job / 'source-switch.json').exists():
            require(digest_file(CLOUD / 'docker-compose.prod.yml') == self.result('source-switch')['compose_sha256'], 'Installed Compose differs')
        print('PRIVATE_DESKTOP_JOB=' + str(self.job), flush=True)
        checkpoints.run(self.perform)


def preflight(bundle, digest, commit):
    identity = stage_bundle(bundle, digest)
    require(identity['source_commit'] == commit, 'Source commit mismatch')
    root = no_links('/opt/xiquan-releases'); root.mkdir(mode=0o700, exist_ok=True); private_directory(root)
    stage = root / ('desktop055-stage-' + uuid.uuid4().hex)
    identity = stage_bundle(bundle, digest, stage)
    print('PRIVATE_DESKTOP_STAGE=' + str(stage), flush=True)
    verify_source(stage / 'xiquan')
    runner = PrivateRunner(stage, lambda: 'preflight')
    state = fresh_state(runner)
    for name in ('xiquan-api-1', 'xiquan-postgres-1'): runner.healthy(name)
    json_write(stage / 'desktop-stage.json', dict(**identity, state=state, protected=protected_files(CLOUD)))
    driver = Desktop055(str(stage)); driver.budget(); driver.validate_compose()
    info = [runner.healthy(n) for n in ('xiquan-api-1', 'xiquan-postgres-1')]
    networks = [n for n in set(info[0]['NetworkSettings']['Networks']) & set(info[1]['NetworkSettings']['Networks'])
                if json.loads(runner(['docker', 'network', 'inspect', n]))[0]['Internal']]
    require(len(networks) == 1, 'One private backend network required')
    driver.job = stage
    driver.context = dict(owner=str(uuid.uuid4()), image_id=info[0]['Image'], network=networks[0])
    write_environment(stage / 'maintenance.env', driver.env)
    snapshot = driver.guard('inspect')
    json_write(stage / 'preflight-snapshot.json', snapshot)
    print(json.dumps(dict(stage=str(stage), phase='preflight', source_commit=commit, source_sha256=digest,
                          target_schema=HEAD)))


def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['preflight', 'deploy', 'resume'])
    for name in ('bundle', 'sha256', 'commit', 'stage', 'job'): parser.add_argument('--' + name)
    args = parser.parse_args()
    driver = None
    try:
        require(os.name == 'posix' and os.getuid() == 0, 'Human-run ECS root only')
        require(re.fullmatch('[0-9a-f]{40}', args.commit or ''), 'Exact source commit required')
        os.umask(0o077)
        import fcntl
        with no_links('/run/lock/xiquan-stock-cutover.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.mode == 'preflight': preflight(args.bundle, args.sha256, args.commit)
            else:
                driver = Desktop055(args.stage, args.job if args.mode == 'resume' else None)
                require(driver.report['source_commit'] == args.commit, 'Explicit source commit differs')
                require(driver.report['bundle_sha256'] == args.sha256, 'Explicit bundle SHA256 differs')
                getattr(driver, args.mode)()
                print('DESKTOP055_PHASE=completed')
    except Exception as error:
        if driver and driver.job:
            path = driver.job / ('failure-' + uuid.uuid4().hex + '.json')
            import traceback
            json_write(path, dict(phase=driver.last_phase, reason=traceback.format_exc()))
            category = re.search(r'category=([a-z0-9]+)', str(error))
            print('DESKTOP055_STOPPED: phase=' + driver.last_phase + ' category=' +
                  (category[1] if category else 'gate') + ' evidence=' + str(path), file=sys.stderr)
            print('PRIVATE_DESKTOP_JOB=' + str(driver.job), file=sys.stderr)
        else:
            reason = str(error) if isinstance(error, DeploymentError) else 'inspect private stage evidence'
            print('DESKTOP055_STOPPED: phase=preflight ' + reason, file=sys.stderr)
        return 1
    finally:
        if driver:
            for restore in driver.restores:
                if restore.started:
                    try: restore.stop()
                    except Exception: pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
