"""Human-run, bounded additive stock cutover. No catalogue/reset/import/publication."""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

from operations_backup_verify import DeploymentError, IsolatedRestore, inspect_database, run, verify_full_restore, wait_healthy, write_environment
from operations_preflight import digest_file, no_links, protected_files, query_cloud_state, stage_bundle
from operations_deploy import Deployment, json_read, json_write, require_single_api, CLOUD, PROJECT, BACKUPS, MOUNT
from operations_offline_build import probe_image, require_dependencies, requirements_digest, expected_payload, stream_build

OLD = '20261004_catalog_packages'
HEAD = '20261005_independent_stock'
TOOLS = ('stock_deploy.py', 'stock_guard.py', 'operations_backup_verify.py',
         'operations_preflight.py', 'operations_deploy.py', 'operations_offline_build.py')
MIB = 1024**2
RESTORE_MEMORY_MIB = 256
MAINTENANCE_MEMORY_MIB = 384
MEMORY_MARGIN_MIB = 128


def require(condition, message):
    if not condition:
        raise DeploymentError(message)


def require_resource_budget(available_bytes, disk_free_bytes, *, include_restore=False):
    required_mib = MAINTENANCE_MEMORY_MIB + MEMORY_MARGIN_MIB
    if include_restore:
        required_mib += RESTORE_MEMORY_MIB
    require(disk_free_bytes >= 6 * 1024**3,
            f'Backup disk insufficient: available={disk_free_bytes // MIB} MiB, required=6144 MiB; no cleanup performed')
    require(available_bytes >= required_mib * MIB,
            f'Available memory insufficient: available={available_bytes // MIB} MiB, required={required_mib} MiB; keep evidence')
    return dict(available_memory_mib=available_bytes // MIB, required_memory_mib=required_mib,
                backup_free_mib=disk_free_bytes // MIB, restore_limit_mib=RESTORE_MEMORY_MIB,
                maintenance_limit_mib=MAINTENANCE_MEMORY_MIB, reserve_mib=MEMORY_MARGIN_MIB)


def check_resources(phase, *, include_restore=False):
    match = re.search(r'^MemAvailable:\s+(\d+)\s+kB', Path('/proc/meminfo').read_text(), re.MULTILINE)
    require(match is not None, 'Cannot determine available physical memory')
    report = require_resource_budget(int(match[1]) * 1024, shutil.disk_usage(BACKUPS).free,
                                     include_restore=include_restore)
    print('STOCK_RESOURCES=' + json.dumps(dict(phase=phase, **report)), flush=True)
    return report


def contract(bundle, digest, commit):
    result = stage_bundle(bundle, digest)
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('xiquan/source-manifest.json'))
        require(manifest.get('asset_source_commit') == commit == manifest['source_commit'] and
                manifest.get('schema_head') == HEAD and manifest.get('desktop_version') == '0.4.4' and
                manifest.get('android_version') == '1.2.3' and manifest.get('android_version_code') == 10 and
                manifest.get('required_migration') == 'server/migrations/versions/' + HEAD + '.py', 'Wrong stock SOURCE contract')
        records = {r['file']: r for r in manifest['files']}
        for tool in TOOLS:
            require(records['deploy/cloud/scripts/' + tool]['sha256'] == digest_file(Path(__file__).parent / tool),
                    'Transport tools differ from committed SOURCE bytes')
    return result


def preflight(bundle, digest, commit):
    contract(bundle, digest, commit)
    state = query_cloud_state()
    require(state['pg_major'] == 17 and state['schema_revision'] == OLD and
            not state['pending_resets'] and not state['business_state']['maintenance'] and
            state['active_policy']['policy_version'] == state['business_state']['policy_version'],
            'PG17 direct predecessor, consistent policy and no reset/maintenance required; open orders are preserved')
    root = no_links('/opt/xiquan-releases')
    root.mkdir(mode=0o700, exist_ok=True)
    require(root.stat().st_uid == 0 and not root.stat().st_mode & 0o077, 'Staging root must be root-owned 0700')
    stage = root / ('stock-stage-' + uuid.uuid4().hex)
    identity = stage_bundle(bundle, digest, stage)
    json_write(stage / 'stock-stage.json', dict(**identity, state=state, protected=protected_files(CLOUD)))
    print(json.dumps(dict(stage=str(stage), source_commit=commit, source_sha256=digest,
                         live_head=state['schema_revision'], open_orders_preserved=state['open_visits'])))


class Restore(IsolatedRestore):
    def start(self):
        env = self.root / (self.name + '.env')
        write_environment(env, dict(POSTGRES_USER='operations_restore', POSTGRES_DB='operations_restore', POSTGRES_PASSWORD=self.password))
        run(['docker', 'volume', 'create', '--label', 'xiquan.operations.restore=' + self.name, self.volume])
        run(['docker', 'run', '-d', '--name', self.name, '--restart', 'no',
             '--memory', f'{RESTORE_MEMORY_MIB}m', '--memory-swap', f'{RESTORE_MEMORY_MIB}m',
             '--cpus', '1', '--pids-limit', '128',
             '--label', 'xiquan.operations.restore=' + self.name, '--network', self.network, '--env-file', str(env),
             '--mount', 'type=volume,src=' + self.volume + ',dst=/var/lib/postgresql/data',
             '--health-cmd', 'pg_isready -U operations_restore -d operations_restore', '--health-interval', '2s',
             '--health-start-period', '20s', '--health-retries', '30', self.image,
             '-c', 'shared_buffers=16MB', '-c', 'work_mem=4MB', '-c', 'maintenance_work_mem=64MB',
             '-c', 'max_connections=20', '-c', 'max_parallel_workers=0', '-c', 'max_parallel_maintenance_workers=0'])
        self.started = True
        wait_healthy(self.name)

    def stop(self):
        super().stop()
        self.started = False


class Stock:
    compose = Deployment.compose
    resolve_environment = Deployment.resolve_environment

    def __init__(self, stage, job=None):
        require(re.fullmatch('/opt/xiquan-releases/stock-stage-[0-9a-f]{32}', stage), 'Invalid exact stage path')
        self.stage = no_links(stage)
        self.source = self.stage / 'xiquan'
        self.manifest = json_read(self.source / 'source-manifest.json')
        self.report = json_read(self.stage / 'stock-stage.json')
        require(self.manifest['source_commit'] == self.report['source_commit'], 'Source identity differs')
        for row in self.manifest['files']:
            file = no_links(self.source / row['file'])
            require(file.stat().st_size == row['size'] and digest_file(file) == row['sha256'], 'Staged source changed')
        for name in TOOLS:
            require(digest_file(self.source / 'deploy/cloud/scripts' / name) == digest_file(Path(__file__).parent / name), 'Invoked tools differ from staged source')
        self.job = no_links(job) if job else None
        self.context = json_read(self.job / 'context.json') if job else {}
        self.api_stop_started = False
        self.resolve_environment()
        self.env.update(RUNTIME_DATABASE_URL=self.normal_env['RUNTIME_DATABASE_URL'], RESET_DATABASE_URL=self.normal_env['RESET_DATABASE_URL'])
        self.restores = []

    def phase(self, name):
        self.last_phase = name
        json_write(self.job / ('phase-' + uuid.uuid4().hex + '.json'), dict(phase=name, source_commit=self.report['source_commit']))
        print('STOCK_PHASE=' + name, flush=True)

    def protected(self):
        require(protected_files(CLOUD) == self.report['protected'], 'Protected download/feed references changed')

    def command(self, args, environment=None, network=None, extra_network=None):
        networks = ['--network', network or self.context['network']]
        if extra_network:
            networks += ['--network', extra_network]
        argv = ['docker', 'run', '--rm', '--user', '0:0',
                    '--memory', f'{MAINTENANCE_MEMORY_MIB}m', '--memory-swap', f'{MAINTENANCE_MEMORY_MIB}m', '--cpus', '1',
                    '--env', 'PYTHONPATH=/app', *networks, '--env-file', str(environment or self.job / 'maintenance.env'),
                    '--mount', 'type=bind,src=' + str(self.job) + ',dst=' + MOUNT,
                    '--mount', 'type=bind,src=' + str(self.source / 'deploy/cloud/scripts/stock_guard.py') + ',dst=/stock_guard.py,readonly',
                    '--entrypoint', 'python', self.context['image_id']] + args
        result = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        if result.returncode:
            evidence = self.job / ('command-failure-' + uuid.uuid4().hex + '.json')
            json_write(evidence, dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
            marker = next((line for line in result.stderr.splitlines() if line.startswith('STOCK_GUARD_STOPPED: ')), None)
            raise DeploymentError((marker or 'Owner command failed; inspect private diagnostics locally') + '; evidence=' + str(evidence))
        return result.stdout.strip()

    def guard(self, mode, environment=None, network=None, baseline=None):
        args = ['/stock_guard.py', mode, '--job', self.context['owner']]
        if baseline:
            args += ['--baseline', MOUNT + '/' + baseline]
        return json.loads(self.command(args, environment, network))

    def build(self, old_image):
        self.phase('before-offline-image')
        expected = requirements_digest((self.source / 'server/requirements.txt').read_bytes())
        require_dependencies(probe_image(old_image, memory_mib=MAINTENANCE_MEMORY_MIB), expected)
        config = json.loads(run(['docker', 'image', 'inspect', old_image]))[0]['Config']
        require(config.get('WorkingDir') == '/app' and config.get('User') == 'xiquan' and
                config.get('Entrypoint') == ['/app/docker-entrypoint.sh'] and config.get('Cmd') == ['python', 'run.py'],
                'Existing image startup contract differs')
        base = 'xiquan-api:stock-base-' + self.context['owner']
        run(['docker', 'tag', old_image, base])
        file = self.job / 'Dockerfile'
        file.write_text('FROM ' + base + '\nUSER root\n'
                        'RUN test -d /app/app && test -d /app/migrations && rm -rf /app/app /app/migrations\n'
                        'COPY --chown=xiquan:xiquan app /app/app\nCOPY --chown=xiquan:xiquan migrations /app/migrations\n'
                        'COPY --chown=xiquan:xiquan run.py docker-entrypoint.sh /app/\n'
                        "RUN sed -i 's/\\r$//' /app/docker-entrypoint.sh && chmod 0755 /app/docker-entrypoint.sh\n"
                        'USER xiquan\nLABEL org.opencontainers.image.revision="' + self.report['source_commit'] + '"\n')
        image = 'xiquan-api:stock-' + self.context['owner']
        stream_build(['docker', 'build', '--pull=false', '--network=none', '-f', str(file), '-t', image,
                      str(self.source / 'server')], self.job / 'build.log')
        proof = probe_image(image, memory_mib=MAINTENANCE_MEMORY_MIB)
        require_dependencies(proof, expected)
        require(proof['payload'] == expected_payload(self.source / 'server'), 'Image source bytes differ')
        self.context['image_id'] = json.loads(run(['docker', 'image', 'inspect', image]))[0]['Id']
        json_write(self.job / 'image.json', dict(image_id=self.context['image_id'], base_id=old_image, requirements_sha256=expected))

    def restore(self, dump):
        require(not any(item.started for item in self.restores), 'Previous restore must stop before starting another')
        check_resources('before-isolated-restore', include_restore=True)
        restore = Restore(self.job, self.context['postgres_image'], self.context['isolated_network'])
        self.restores.append(restore)
        restore.start()
        restore.restore(dump)
        return restore

    def backup(self, name):
        self.phase('before-' + name + '-backup-restore')
        folder = self.job / name
        folder.mkdir(mode=0o700)
        self.command(['-m', 'flask', '--app', 'run.py', 'operations-backup', 'create', '--output', MOUNT + '/' + name])
        dump = folder / 'database.backup'
        restore = self.restore(dump)
        verify_full_restore(inspect_database('xiquan-postgres-1'), inspect_database(restore.name))
        verification = self.job / (name + '-restore.env')
        write_environment(verification, dict(self.env, XIQUAN_RESTORE_DATABASE_URL=restore.database_url))
        # Only the one-shot verifier joins both networks; clone retains its dedicated private network.
        self.command(['-m', 'flask', '--app', 'run.py', 'operations-backup', 'verify-restored',
                      '--database-url-env', 'XIQUAN_RESTORE_DATABASE_URL', '--receipt', MOUNT + '/' + name + '/candidate.json'],
                     verification, extra_network=self.context['isolated_network'])
        receipt = json_read(folder / 'receipt.json')
        require(receipt['restore']['status'] == 'verified' and digest_file(dump) == receipt['dump_sha256'], 'Restore receipt mismatch')
        return restore

    def rehearsal(self, restore):
        self.phase('before-isolated-migration-roles-concurrency')
        passwords = {role: secrets.token_urlsafe(48) for role in ('xiquan_app', 'xiquan_reset', 'xiquan_backup')}
        file = self.job / 'clone-login.sql'
        file.write_text(''.join("CREATE ROLE " + role + " LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '" + password + "';\n" for role, password in passwords.items()))
        file.chmod(0o600)
        run(['docker', 'exec', '-i', restore.name, 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1',
             '-U', 'operations_restore', '-d', 'operations_restore'], input_file=file)
        url = lambda role: 'postgresql+psycopg://' + role + ':' + quote(passwords[role], safe='') + '@' + restore.name + ':5432/operations_restore'
        env = self.job / 'clone.env'
        write_environment(env, dict(self.env, DATABASE_URL=restore.database_url, RUNTIME_DATABASE_URL=url('xiquan_app'),
                                   RESET_DATABASE_URL=url('xiquan_reset'), RESET_BACKUP_DATABASE_URL=url('xiquan_backup')))
        migrated = self.guard('migrate', env, self.context['isolated_network'])
        json_write(self.job / 'clone-preserved-before-fixtures.json', migrated)
        # Current role scripts reference new tables: initialize grants only AFTER clone migration.
        for role_file in ('runtime-role.sql', 'reset-role.sql', 'backup-role.sql'):
            run(['docker', 'exec', '-i', restore.name, 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1',
                 '-U', 'operations_restore', '-d', 'operations_restore'], input_file=self.source / 'deploy/cloud/scripts' / role_file)
        login = self.job / 'clone-enable-login.sql'
        login.write_text(''.join('ALTER ROLE ' + role + ' LOGIN;\n' for role in passwords))
        login.chmod(0o600)
        run(['docker', 'exec', '-i', restore.name, 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1',
             '-U', 'operations_restore', '-d', 'operations_restore'], input_file=login)
        proof = self.guard('proof', env, self.context['isolated_network'])
        json_write(self.job / 'clone-proof.json', proof)
        restore.stop()
        self.phase('isolated-gates-complete')

    def install(self):
        self.phase('before-source-asset-switch')
        for record in self.manifest['files']:
            relative = record['file']
            if not relative.startswith('server/'):
                continue
            self.copy(record, PROJECT / relative, 0o644)
        for area, target in [('client', CLOUD / 'web'), ('mobile', CLOUD / 'mobile')]:
            records = [row for row in self.manifest['files'] if row['file'].startswith(area + '/dist/')]
            for record in sorted(records, key=lambda row: row['file'].endswith('/index.html')):
                relative = record['file'].split('/dist/', 1)[1]
                require(not relative.startswith('downloads/') and relative != 'download-config.json', 'Protected public content')
                self.copy(record, target / relative, 0o644)
        # Future compose restarts use the same verified new image, even without our override.
        run(['docker', 'tag', self.context['image_id'], 'xiquan-api:owner-reset'])
        self.phase('source-switched')

    def copy(self, record, target, mode):
        target = no_links(target)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        if '/web/' in str(target) or '/mobile/' in str(target):
            for parent in [target.parent, *target.parent.parents]:
                if parent == CLOUD:
                    break
                parent.chmod(0o755)
        if target.exists():
            old = self.job / 'old-files' / target.relative_to(PROJECT)
            old.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not old.exists():
                shutil.copy2(target, old)
                old.chmod(0o600)
        tmp = target.with_name(target.name + '.stock-' + self.context['owner'])
        with tmp.open('xb') as writer, (self.source / record['file']).open('rb') as reader:
            shutil.copyfileobj(reader, writer)
        tmp.chmod(mode)
        require(digest_file(tmp) == record['sha256'], 'Source copy hash mismatch')
        os.replace(tmp, target)

    def finish(self):
        self.protected()
        require(digest_file(CLOUD / '.env') == self.context['env_sha256'] and
                digest_file(CLOUD / 'docker-compose.prod.yml') == self.context['compose_sha256'], 'Private configuration changed before restart')
        override = self.job / 'image-override.json'
        if not override.exists():
            json_write(override, {'services': {'api': {'image': self.context['image_id']}}})
        self.phase('before-api-start')
        self.compose('up', '-d', '--no-deps', '--no-build', 'api', override=override)
        wait_healthy('xiquan-api-1', timeout=180)
        require_single_api(run(['docker', 'ps', '--filter', 'label=com.docker.compose.project=xiquan',
                                '--filter', 'label=com.docker.compose.service=api', '--format', '{{json .}}']))
        api = json.loads(run(['docker', 'inspect', 'xiquan-api-1']))[0]
        require(api['Image'] == self.context['image_id'], 'Running image differs')
        actual = dict(v.split('=', 1) for v in api['Config']['Env'] if '=' in v)
        require(all(actual.get(k, '0') == '0' for k in ('AUTO_CREATE_DB', 'RUN_MIGRATIONS', 'SEED_DEFAULTS')) and
                all(actual.get(k, '1') == '1' for k in ('API_WORKERS', 'WEB_CONCURRENCY', 'API_REPLICAS')) and
                'MAINTENANCE_DATABASE_URL' not in actual and
                all(actual.get(k) == self.normal_env.get(k) for k in ('DATABASE_URL', 'SECRET_KEY', 'JWT_SECRET_KEY', 'AUDIT_HMAC_KEY')),
                'Runtime credentials/startup contract changed')
        run(['docker', 'exec', 'xiquan-nginx-1', 'nginx', '-t'])
        run(['docker', 'exec', 'xiquan-nginx-1', 'nginx', '-s', 'reload'])
        health = json.loads(run(['curl', '--fail', '--silent', '--show-error', '--max-time', '20', 'https://api.pqxqxy.xyz/api/health']))
        require(health.get('success') and health.get('data', {}).get('database') == 'ok', 'Public health failed')
        # Public bytes, including all referenced assets, must equal the reviewed source.
        for record in self.manifest['files']:
            for area, route in [('client/dist/', '/app/'), ('mobile/dist/', '/mobile/')]:
                if record['file'].startswith(area):
                    relative = record['file'][len(area):]
                    require(re.fullmatch('[A-Za-z0-9_./-]+', relative), 'Invalid public asset path')
                    output = self.job / ('public-' + uuid.uuid4().hex)
                    run(['curl', '--fail', '--silent', '--show-error', '--max-time', '30', '--output', str(output),
                         'https://api.pqxqxy.xyz' + route + relative])
                    require(digest_file(output) == record['sha256'], 'Public asset hash differs')
        for relative, record in self.report['protected'].items():
            if relative.startswith(('mobile/downloads/', 'updates/', 'releases/')) or relative == 'mobile/download-config.json':
                output = self.job / ('retained-public-' + uuid.uuid4().hex)
                run(['curl', '--fail', '--silent', '--show-error', '--max-time', '60', '--output', str(output),
                     'https://api.pqxqxy.xyz/' + relative])
                require(digest_file(output) == record['sha256'], 'Retained public download/feed differs')
        self.protected()
        self.guard('release', baseline='after.json')
        self.phase('maintenance-released')
        json_write(self.job / 'completed.json', dict(source_commit=self.report['source_commit'], image_id=self.context['image_id'],
                   schema=HEAD, installer_publication=False, photo_import=False, real_device_acceptance_pending=True))
        print('STOCK_SOURCE_DEPLOYED; human login/import/device acceptance/publication remain pending')

    def deploy(self):
        self.protected()
        current = query_cloud_state()
        require(current['schema_revision'] == OLD and not current['pending_resets'] and not current['business_state']['maintenance'],
                'Head/reset/maintenance changed; no takeover')
        info = json.loads(run(['docker', 'inspect', 'xiquan-api-1', 'xiquan-postgres-1']))
        require(all(i['State']['Running'] and i['State'].get('Health', {}).get('Status') == 'healthy' for i in info), 'Current services unhealthy')
        common = set(info[0]['NetworkSettings']['Networks']) & set(info[1]['NetworkSettings']['Networks'])
        network = [n for n in common if json.loads(run(['docker', 'network', 'inspect', n]))[0]['Internal']]
        require(len(network) == 1, 'One private backend network required')
        require_single_api(run(['docker', 'ps', '--filter', 'label=com.docker.compose.project=xiquan', '--filter', 'label=com.docker.compose.service=api', '--format', '{{json .}}']))
        running_env = dict(v.split('=', 1) for v in info[0]['Config']['Env'] if '=' in v)
        require(all(running_env.get(k) == self.normal_env.get(k) for k in ('SECRET_KEY', 'JWT_SECRET_KEY', 'AUDIT_HMAC_KEY', 'DATABASE_URL')), 'Existing identity changed')
        check_resources('before-offline-build')
        owner = str(uuid.uuid4())
        self.job = no_links(BACKUPS / ('stock-cutover-' + owner.replace('-', '')))
        self.job.mkdir(mode=0o700)
        print('PRIVATE_STOCK_JOB=' + str(self.job), flush=True)
        self.context = dict(owner=owner, stage=str(self.stage), source_commit=self.report['source_commit'], network=network[0],
                            isolated_network='xiquan-stock-proof-' + owner, postgres_image=info[1]['Image'], old_image=info[0]['Image'],
                            env_sha256=digest_file(CLOUD / '.env'), compose_sha256=digest_file(CLOUD / 'docker-compose.prod.yml'),
                            tools={name: digest_file(Path(__file__).parent / name) for name in TOOLS})
        write_environment(self.job / 'maintenance.env', self.env)
        self.build(info[0]['Image'])
        json_write(self.job / 'context.json', self.context)
        run(['docker', 'network', 'create', '--internal', self.context['isolated_network']])
        self.guard('inspect')  # Actual owner/roles/audit/PG17 checks before stopping normal API.
        check_resources('before-stop-api', include_restore=True)
        self.phase('before-stop-api')
        self.api_stop_started = True
        self.compose('stop', 'api')
        require(not json.loads(run(['docker', 'inspect', 'xiquan-api-1']))[0]['State']['Running'], 'API still running')
        check_resources('after-stop-api', include_restore=True)
        self.phase('before-maintenance-claim')
        json_write(self.job / 'before.json', self.guard('claim'))
        self.phase('maintenance-owned')
        clone = self.backup('before')
        self.rehearsal(clone)
        require(self.guard('inspect') == json_read(self.job / 'before.json'), 'Production changed during isolated proof')
        self.phase('before-production-migration')
        check_resources('before-production-migration')
        json_write(self.job / 'after.json', self.guard('migrate', baseline='before.json'))
        self.phase('production-migrated')
        self.backup('after').stop()
        json_write(self.job / 'ready.json', dict(source_commit=self.report['source_commit'], image_id=self.context['image_id']))
        self.phase('ready-to-switch')
        self.install()
        self.finish()

    def resume(self):
        check_resources('resume-ready-checkpoint')
        require(re.fullmatch('/opt/xiquan-backups/stock-cutover-[0-9a-f]{32}', str(self.job)), 'Invalid job')
        require(self.job.stat().st_uid == 0 and not self.job.stat().st_mode & 0o077, 'Private root-owned job required')
        require(self.context['stage'] == str(self.stage) and self.context['source_commit'] == self.report['source_commit'] and
                self.context['tools'] == {name: digest_file(Path(__file__).parent / name) for name in TOOLS}, 'Job/source/tool identity changed')
        require(digest_file(CLOUD / '.env') == self.context['env_sha256'] and
                digest_file(CLOUD / 'docker-compose.prod.yml') == self.context['compose_sha256'], 'Private configuration changed')
        ready = json_read(self.job / 'ready.json')
        require(ready['image_id'] == self.context['image_id'], 'Ready image changed')
        require(not (self.job / 'completed.json').exists(), 'Already completed')
        # Only the fully backed-up postmigration checkpoint supports resume; never rebuild or repeat DDL.
        require(query_cloud_state()['schema_revision'] == HEAD and self.guard('inspect') == json_read(self.job / 'after.json'),
                'Unsupported partial state; retain evidence and investigate')
        self.protected()
        self.api_stop_started = True
        self.compose('stop', 'api')
        require(json.loads(run(['docker', 'image', 'inspect', self.context['image_id']]))[0]['Id'] == self.context['image_id'], 'Pinned image missing')
        self.install()
        self.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['preflight', 'deploy', 'resume'])
    parser.add_argument('--bundle')
    parser.add_argument('--sha256')
    parser.add_argument('--commit')
    parser.add_argument('--stage')
    parser.add_argument('--job')
    args = parser.parse_args()
    deployment = None
    try:
        require(os.name == 'posix' and os.getuid() == 0, 'Human-run ECS root only')
        os.umask(0o077)
        import fcntl
        lock = no_links('/run/lock/xiquan-stock-cutover.lock')
        with lock.open('a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.mode == 'preflight':
                preflight(args.bundle, args.sha256, args.commit)
            else:
                deployment = Stock(args.stage, args.job if args.mode == 'resume' else None)
                require(deployment.report['source_commit'] == args.commit, 'Explicit commit differs from stage')
                if args.mode == 'deploy':
                    deployment.deploy()
                else:
                    deployment.resume()
    except Exception as error:
        failed_phase = getattr(deployment, 'last_phase', 'read-only-precheck')
        if deployment and deployment.api_stop_started and deployment.job and (deployment.job / 'context.json').exists():
            try:
                # Do not clear maintenance or start old code after any failure.
                deployment.compose('stop', 'api')
                deployment.phase('stopped-retain-owned-maintenance-and-evidence')
            except Exception:
                pass
        message = str(error) if isinstance(error, DeploymentError) else 'Gate failed; inspect private checkpoint. No automatic restore, clear or old-API restart.'
        print('STOCK_STOPPED: ' + message, file=sys.stderr)
        if deployment and deployment.job:
            print('PRIVATE_STOCK_EVIDENCE=' + str(deployment.job), file=sys.stderr)
            print('FAILED_PHASE=' + failed_phase, file=sys.stderr)
            print('Resume supports only ready.json + exact after.json + owned maintenance. Otherwise stop for checkpoint-specific recovery.', file=sys.stderr)
        return 1
    finally:
        if deployment:
            for restore in deployment.restores:
                try:
                    restore.stop()
                except Exception:
                    pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
