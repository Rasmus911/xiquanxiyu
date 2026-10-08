"""Human-run additive registration cutover. No business conversion or feed publication."""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

from stock_deploy import Stock, check_resources, require
from operations_backup_verify import DeploymentError, run, wait_healthy, write_environment
from operations_preflight import stage_bundle, no_links, digest_file, protected_files, query_cloud_state
from operations_deploy import CLOUD, PROJECT, BACKUPS, MOUNT, json_read, json_write, require_single_api
from urllib.parse import quote
from operations_offline_build import probe_image, require_dependencies, requirements_digest, expected_payload

OLD = '20261007_ordering_cost'
HEAD = '20261008_registration_token'
TOOLS = ('desktop_049_deploy.py', 'desktop_049_guard.py', 'stock_deploy.py', 'stock_guard.py',
         'operations_backup_verify.py', 'operations_preflight.py', 'operations_deploy.py', 'operations_offline_build.py')


def ensure_registration_secret(environment, backup):
    """Remote private environment only. Never log the returned value."""
    environment, backup = no_links(environment), no_links(backup)
    content = environment.read_text(encoding='utf-8')
    matches = re.findall(r'^REGISTRATION_TOKEN_SECRET=(.*)$', content, re.MULTILINE)
    require(len(matches) <= 1, 'Duplicate registration secret configuration')
    if matches:
        value = matches[0].strip().strip('"').strip("'")
        require(len(value.encode('utf-8')) >= 32 and not value.startswith('CHANGE_ME') and
                not any(char in value for char in '\r\n$'), 'Existing registration secret invalid; retain evidence for private correction')
    else:
        value = secrets.token_urlsafe(48)
    if not backup.exists():
        with backup.open('xb') as writer:
            writer.write(environment.read_bytes())
        backup.chmod(0o600)
    if not matches:
        temporary = environment.with_name(environment.name + '.registration-' + uuid.uuid4().hex)
        with temporary.open('x', encoding='utf-8', newline='\n') as writer:
            writer.write(content.rstrip('\n') + '\nREGISTRATION_TOKEN_SECRET=' + value + '\n')
            writer.flush()
            os.fsync(writer.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, environment)
    environment.chmod(0o600)
    return value


def verify_source(source):
    manifest = json_read(source / 'source-manifest.json')
    records = {row['file']: row for row in manifest['files']}
    require(len(records) == len(manifest['files']), 'Duplicate SOURCE records')
    require('server/app/registration_service.py' in records and
            'server/migrations/versions/' + HEAD + '.py' in records, 'Reviewed registration source missing')
    for row in manifest['files']:
        from operations_preflight import safe_relative
        safe_relative(row['file'])
        file = no_links(source / row['file'])
        require(file.stat().st_size == row['size'] and digest_file(file) == row['sha256'], 'Staged bytes changed')
    require(json_read(source / 'client/package.json')['version'] == '0.4.9', 'Wrong renderer version')
    mobile = json_read(source / 'mobile/version.json')
    require(mobile['version'] == '1.2.7' and mobile['versionCode'] == 14, 'Wrong Android source version')
    for name in TOOLS:
        require('deploy/cloud/scripts/' + name in records and
                digest_file(source / 'deploy/cloud/scripts' / name) == digest_file(Path(__file__).parent / name),
                'Transport tool differs from exact committed SOURCE')
    return manifest


def fresh_state():
    state = query_cloud_state()
    require(state['pg_major'] == 17 and state['schema_revision'] == OLD and not state['pending_resets'] and
            not state['business_state']['maintenance'] and
            state['business_state']['policy_version'] == state['active_policy']['policy_version'],
            'Expected healthy 0.4.8 schema, matching access policy and no pending reset/maintenance')
    return state


def preflight(bundle, digest, commit):
    identity = stage_bundle(bundle, digest)
    require(identity['source_commit'] == commit, 'Source commit mismatch')
    state = fresh_state()
    root = no_links('/opt/xiquan-releases')
    root.mkdir(mode=0o700, exist_ok=True)
    require(root.stat().st_uid == 0 and not root.stat().st_mode & 0o077, 'Private stage root required')
    stage = root / ('desktop049-stage-' + uuid.uuid4().hex)
    identity = stage_bundle(bundle, digest, stage)
    verify_source(stage / 'xiquan')
    json_write(stage / 'desktop-stage.json', dict(**identity, state=state, protected=protected_files(CLOUD)))
    print(json.dumps(dict(stage=str(stage), source_commit=commit, source_sha256=digest,
                          schema=state['schema_revision'], open_orders_preserved=state['open_visits'])))


class Desktop049(Stock):
    def __init__(self, stage, job=None):
        require(re.fullmatch('/opt/xiquan-releases/desktop049-stage-[0-9a-f]{32}', stage), 'Invalid exact stage path')
        self.stage = no_links(stage)
        require(self.stage.stat().st_uid == 0 and not self.stage.stat().st_mode & 0o077, 'Private root-owned stage required')
        self.source = self.stage / 'xiquan'
        self.manifest = verify_source(self.source)
        self.report = json_read(self.stage / 'desktop-stage.json')
        require(self.report['source_commit'] == self.manifest['source_commit'], 'Stage identity changed')
        if job:
            require(re.fullmatch('/opt/xiquan-backups/desktop049-cutover-[0-9a-f]{32}', job), 'Invalid exact recovery job')
        self.job = no_links(job) if job else None
        if self.job:
            require(self.job.stat().st_uid == 0 and not self.job.stat().st_mode & 0o077, 'Private root-owned recovery job required')
        self.context = json_read(self.job / 'context.json') if job else {}
        self.restores = []
        self.api_stop_started = False
        self.resolve_environment()
        self.env.update(RUNTIME_DATABASE_URL=self.normal_env['RUNTIME_DATABASE_URL'],
                        RESET_DATABASE_URL=self.normal_env['RESET_DATABASE_URL'])

    def validate_compose_change(self):
        configs = []
        for file in (CLOUD / 'docker-compose.prod.yml', self.source / 'deploy/cloud/docker-compose.prod.yml'):
            config = json.loads(run(['docker','compose','--env-file',str(CLOUD / '.env'),'-p','xiquan',
                                    '-f',str(file),'--profile','maintenance','config','--format','json']))
            # Build context paths differ with staging; no build is invoked through compose.
            config['services']['api'].pop('build', None)
            config['services']['api']['environment'].pop('REGISTRATION_TOKEN_SECRET', None)
            # Docker resolves relative bind mounts against the respective compose directory.
            for service in config['services'].values():
                for mount in service.get('volumes', []):
                    value = mount.get('source', '')
                    try:
                        relative = Path(value).relative_to(self.source)
                    except ValueError:
                        continue
                    mount['source'] = str(PROJECT / relative)
            configs.append(config)
        require(configs[0] == configs[1], 'Compose differs beyond registration capability; inspect before stop')

    def install(self):
        super().install()
        record = next(row for row in self.manifest['files'] if row['file'] == 'deploy/cloud/docker-compose.prod.yml')
        self.copy(record, CLOUD / 'docker-compose.prod.yml', 0o600)
        self.context['compose_sha256'] = digest_file(CLOUD / 'docker-compose.prod.yml')
        json_write(self.job / 'context.json', self.context)

    def rehearsal(self, restore):
        self.phase('isolated-additive-migration-and-pg17-security')
        passwords = {role: secrets.token_urlsafe(48) for role in ('xiquan_app','xiquan_reset','xiquan_backup')}
        sql = self.job / 'clone-logins.sql'
        sql.write_text(''.join("CREATE ROLE " + role + " LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '" + password + "';\n" for role,password in passwords.items()))
        sql.chmod(0o600)
        run(['docker','exec','-i',restore.name,'psql','-X','-q','-v','ON_ERROR_STOP=1','-U','operations_restore','-d','operations_restore'], input_file=sql)
        url = lambda role: 'postgresql+psycopg://' + role + ':' + quote(passwords[role], safe='') + '@' + restore.name + ':5432/operations_restore'
        env = self.job / 'clone.env'
        write_environment(env, dict(self.env, DATABASE_URL=restore.database_url, RUNTIME_DATABASE_URL=url('xiquan_app'),
                                  RESET_DATABASE_URL=url('xiquan_reset'), RESET_BACKUP_DATABASE_URL=url('xiquan_backup')))
        json_write(self.job / 'clone-before.json', self.guard('inspect', env, self.context['isolated_network']))
        migrated = self.guard('migrate', env, self.context['isolated_network'], baseline='clone-before.json')
        json_write(self.job / 'clone-preserved-before-fixtures.json', migrated)
        for name in ('runtime-role.sql','reset-role.sql','backup-role.sql'):
            run(['docker','exec','-i',restore.name,'psql','-X','-q','-v','ON_ERROR_STOP=1','-U','operations_restore','-d','operations_restore'], input_file=self.source / 'deploy/cloud/scripts' / name)
        sql = self.job / 'clone-enable-logins.sql'
        sql.write_text(''.join('ALTER ROLE ' + role + ' LOGIN;\n' for role in passwords))
        sql.chmod(0o600)
        run(['docker','exec','-i',restore.name,'psql','-X','-q','-v','ON_ERROR_STOP=1','-U','operations_restore','-d','operations_restore'], input_file=sql)
        proof = self.guard('proof', env, self.context['isolated_network'])
        require(all(proof.get(key) is True for key in ('pg17','isolated','one_use','expiry_after_lock','immutable','runtime_grants')), 'Incomplete isolated PostgreSQL proof')
        json_write(self.job / 'clone-proof.json', proof)
        restore.stop()

    def phase(self, name):
        self.last_phase = name
        if self.job:
            json_write(self.job / ('phase-' + uuid.uuid4().hex + '.json'), {'phase':name})
        print('DESKTOP_PHASE=' + name, flush=True)

    def command(self, args, environment=None, network=None, extra_network=None):
        networks = ['--network', network or self.context['network']]
        if extra_network:
            networks += ['--network', extra_network]
        command = ['docker', 'run', '--rm', '--user', '0:0', '--memory', '384m', '--memory-swap', '384m',
                   '--cpus', '1', '--env', 'PYTHONPATH=/app', *networks,
                   '--env-file', str(environment or self.job / 'maintenance.env'),
                   '--mount', 'type=bind,src=' + str(self.job) + ',dst=' + MOUNT,
                   '--mount', 'type=bind,src=' + str(self.source / 'deploy/cloud/scripts/desktop_049_guard.py') + ',dst=/desktop_guard.py,readonly',
                   '--mount', 'type=bind,src=' + str(self.source / 'deploy/cloud/scripts/stock_guard.py') + ',dst=/stock_guard.py,readonly',
                   '--entrypoint', 'python', self.context['image_id'], *args]
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if result.returncode:
            path = self.job / ('command-failure-' + uuid.uuid4().hex + '.json')
            json_write(path, {'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            marker = next((line for line in result.stderr.splitlines() if line.startswith('DESKTOP_GUARD_STOPPED: ')), None)
            raise DeploymentError((marker or 'Owner command failed') + '; private evidence=' + str(path))
        return result.stdout.strip()

    def guard(self, mode, environment=None, network=None, baseline=None):
        args = ['/desktop_guard.py', mode, '--job', self.context['owner']]
        if baseline:
            args += ['--baseline', MOUNT + '/' + baseline]
        return json.loads(self.command(args, environment, network))

    def stop_writes_with_restore_budget(self, original_api):
        fresh_state()
        check_resources('desktop049-before-stop-api')
        self.verify_pinned_image()
        require(self.guard('inspect') == self.pre_stop_snapshot, 'Business snapshot changed before API stop; repeat preflight')
        # The live API still uses RAM here. Budget the one-shot prechecks first,
        # then measure the full 768 MiB restore budget after stopping its writes.
        # No maintenance claim, backup or migration has happened at this point.
        self.phase('stop-api-writes')
        self.compose('stop', 'api')
        self.api_stop_started = True
        try:
            check_resources('desktop049-after-stop-before-backup', include_restore=True)
        except DeploymentError:
            # Restart is safe ONLY in this pre-claim phase and for the exact old
            # container/image/config with the untouched old database schema.
            fresh_state()
            current = json.loads(run(['docker', 'inspect', original_api['Id']]))[0]
            require(current['Id'] == original_api['Id'] and current['Image'] == original_api['Image'] and
                    current['Config'] == original_api['Config'] and not current['State']['Running'],
                    'Original API identity changed; no automatic restart')
            self.phase('restore-original-api-before-any-database-change')
            run(['docker', 'start', original_api['Id']])
            wait_healthy('xiquan-api-1', timeout=180)
            self.api_stop_started = False
            raise

    def verify_pinned_image(self):
        proof = probe_image(self.context['image_id'], memory_mib=384)
        require_dependencies(proof, requirements_digest((self.source / 'server/requirements.txt').read_bytes()))
        require(proof['payload'] == expected_payload(self.source / 'server'), 'Image source bytes differ')

    def finish(self):
        self.protected()
        require(digest_file(CLOUD / '.env') == self.context['env_sha256'] and
                digest_file(CLOUD / 'docker-compose.prod.yml') == self.context['compose_sha256'], 'Private configuration changed')
        # Health/config check of the new API happens under owned maintenance with its worker disabled.
        if not (self.job / 'api-verified.json').exists():
            self.phase('start-pinned-api-under-owned-maintenance')
            paused = self.job / 'worker-paused-image.json'
            json_write(paused, {'services': {'api': {'image': self.context['image_id'], 'environment': {'RESET_WORKER_ENABLED':'0'}}}})
            self.compose('up','-d','--no-deps','--no-build','api', override=paused)
            wait_healthy('xiquan-api-1', timeout=180)
            api = json.loads(run(['docker','inspect','xiquan-api-1']))[0]
            environment = dict(value.split('=',1) for value in api['Config']['Env'] if '=' in value)
            require(api['Image'] == self.context['image_id'] and environment.get('RESET_WORKER_ENABLED') == '0' and
                    environment.get('REGISTRATION_TOKEN_SECRET') == self.normal_env.get('REGISTRATION_TOKEN_SECRET') and
                    len(environment.get('REGISTRATION_TOKEN_SECRET','').encode()) >= 32, 'Paused API registration configuration invalid')
            run(['docker','exec','xiquan-nginx-1','nginx','-t'])
            run(['docker','exec','xiquan-nginx-1','nginx','-s','reload'])
            json_write(self.job / 'api-verified.json', {'image_id':self.context['image_id']})
        # Release ONLY this proven job before starting normal reset recovery.
        # The normal worker starts only after this owned maintenance release.
        released = self.job / 'maintenance-released.json'
        if not released.exists():
            self.phase('release-owned-maintenance-before-normal-worker-start')
            json_write(released, self.guard('release', baseline='after.json'))
        self.phase('start-verified-normal-api')
        override = self.job / 'image-override.json'
        if not override.exists():
            json_write(override, {'services': {'api': {'image': self.context['image_id'],
                        'environment': {'RESET_WORKER_ENABLED':'1'}}}})
        # Failure leaves the pinned API intact. Never stop a healthy service in an exception handler.
        self.compose('up', '-d', '--no-deps', '--no-build', 'api', override=override)
        wait_healthy('xiquan-api-1', timeout=180)
        require_single_api(run(['docker','ps','--filter','label=com.docker.compose.project=xiquan',
                                '--filter','label=com.docker.compose.service=api','--format','{{json .}}']))
        api = json.loads(run(['docker','inspect','xiquan-api-1']))[0]
        require(api['Image'] == self.context['image_id'], 'Running image differs from verified SOURCE')
        environment = dict(value.split('=',1) for value in api['Config']['Env'] if '=' in value)
        require(environment.get('RESET_WORKER_ENABLED') == '1' and
                environment.get('REGISTRATION_TOKEN_SECRET') == self.normal_env.get('REGISTRATION_TOKEN_SECRET') and
                all(environment.get(key,'') == self.normal_env.get(key,'') for key in
                    ('DATABASE_URL','SECRET_KEY','JWT_SECRET_KEY','AUDIT_HMAC_KEY')) and
                all(environment.get(key,'0') == '0' for key in ('RUN_MIGRATIONS','SEED_DEFAULTS','AUTO_CREATE_DB')) and
                'MAINTENANCE_DATABASE_URL' not in environment, 'Runtime identity/startup flags changed')
        run(['docker','exec','xiquan-nginx-1','nginx','-t'])
        run(['docker','exec','xiquan-nginx-1','nginx','-s','reload'])
        health = json.loads(run(['curl','--fail','--silent','--show-error','--max-time','20',
                                  'https://api.pqxqxy.xyz/api/health']))
        require(health.get('success') and health.get('data',{}).get('database') == 'ok', 'Public health failed')
        for relative, route in [('client/dist/index.html','app/index.html'),('mobile/dist/index.html','mobile/index.html')]:
            output = self.job / ('public-index-' + uuid.uuid4().hex)
            run(['curl','--fail','--silent','--show-error','--max-time','20','--output',str(output),
                 'https://api.pqxqxy.xyz/' + route])
            require(digest_file(output) == digest_file(self.source / relative), 'Public renderer differs')
        self.protected()
        json_write(self.job / 'completed.json', {'source_commit':self.report['source_commit'],
                   'image_id':self.context['image_id'],'schema':HEAD,'installer_publication':False})
        print('DESKTOP049_API_WEB_DEPLOYED; desktop signed-channel publication and human acceptance remain.')

    def deploy(self):
        self.protected()
        fresh_state()
        self.validate_compose_change()
        info = json.loads(run(['docker','inspect','xiquan-api-1','xiquan-postgres-1']))
        require(all(row['State']['Running'] and row['State'].get('Health',{}).get('Status') == 'healthy' for row in info),
                'Existing services must be healthy')
        running = dict(value.split('=',1) for value in info[0]['Config']['Env'] if '=' in value)
        require(all(running.get(key,'') == self.normal_env.get(key,'') for key in
                    ('DATABASE_URL','SECRET_KEY','JWT_SECRET_KEY','AUDIT_HMAC_KEY')), 'Runtime identity differs')
        common = set(info[0]['NetworkSettings']['Networks']) & set(info[1]['NetworkSettings']['Networks'])
        private = [name for name in common if json.loads(run(['docker','network','inspect',name]))[0]['Internal']]
        require(len(private) == 1, 'One private backend network required')
        require_single_api(run(['docker','ps','--filter','label=com.docker.compose.project=xiquan',
                                '--filter','label=com.docker.compose.service=api','--format','{{json .}}']))
        check_resources('desktop049-before-offline-build')
        owner = str(uuid.uuid4())
        self.job = no_links(BACKUPS / ('desktop049-cutover-' + owner.replace('-','')))
        self.job.mkdir(mode=0o700)
        print('PRIVATE_DESKTOP_JOB=' + str(self.job), flush=True)
        self.phase('private-registration-secret-setup')
        ensure_registration_secret(CLOUD / '.env', self.job / 'environment-before-registration.env')
        self.resolve_environment()
        self.env.update(RUNTIME_DATABASE_URL=self.normal_env['RUNTIME_DATABASE_URL'], RESET_DATABASE_URL=self.normal_env['RESET_DATABASE_URL'])
        self.context = dict(owner=owner,stage=str(self.stage),source_commit=self.report['source_commit'],network=private[0],
                            isolated_network='xiquan-desktop-proof-' + owner,postgres_image=info[1]['Image'],
                            env_sha256=digest_file(CLOUD / '.env'),compose_sha256=digest_file(CLOUD / 'docker-compose.prod.yml'),
                            tools={name:digest_file(Path(__file__).parent / name) for name in TOOLS})
        write_environment(self.job / 'maintenance.env', self.env)
        self.build(info[0]['Image'])
        json_write(self.job / 'context.json', self.context)
        run(['docker','network','create','--internal',self.context['isolated_network']])
        self.pre_stop_snapshot = self.guard('inspect')
        self.stop_writes_with_restore_budget(info[0])
        json_write(self.job / 'before.json', self.guard('claim'))
        clone = self.backup('before')
        self.rehearsal(clone)
        require(self.guard('inspect') == json_read(self.job / 'before.json'), 'Production changed during isolated rehearsal')
        self.phase('additive-registration-schema')
        json_write(self.job / 'after.json', self.guard('migrate', baseline='before.json'))
        self.backup('after').stop()
        json_write(self.job / 'ready.json', {'image_id':self.context['image_id'],'source_commit':self.report['source_commit']})
        self.install()
        self.finish()

    def resume(self):
        self.phase('classify-resume-checkpoint')
        self.verify_pinned_image()
        require(self.context['stage'] == str(self.stage) and self.context['source_commit'] == self.report['source_commit'] and
                self.context['tools'] == {name:digest_file(Path(__file__).parent / name) for name in TOOLS}, 'Recovery source/tool identity differs')
        require(not (self.job / 'completed.json').exists(), 'Already completed; do not redeploy')
        current = query_cloud_state()
        require(current['schema_revision'] == HEAD, 'Pre-migration checkpoint: no automatic replay/restore; inspect retained phase and backup')
        require((self.job / 'after.json').exists(), 'Post-migration result missing: stop for checkpoint-specific recovery; never restart old API')
        if not (self.job / 'ready.json').exists():
            require(self.guard('inspect') == json_read(self.job / 'after.json'), 'Post-migration checkpoint changed')
            require(not (self.job / 'after').exists(), 'Incomplete post-migration backup: retain evidence for checkpoint-specific recovery')
            self.backup('after').stop()
            json_write(self.job / 'ready.json', {'image_id':self.context['image_id'],'source_commit':self.report['source_commit']})
        ready = json_read(self.job / 'ready.json')
        require(ready['image_id'] == self.context['image_id'] and ready['source_commit'] == self.report['source_commit'], 'Ready identity differs')
        state = query_cloud_state()
        require(state['schema_revision'] == HEAD and not state['pending_resets'], 'Unsupported recovery schema/reset state')
        if (self.job / 'maintenance-released.json').exists():
            require(not state['business_state']['maintenance'], 'Another maintenance task exists')
            # Source is already switched in this checkpoint. No writes/migration/stop repeated.
        else:
            require(self.guard('inspect') == json_read(self.job / 'after.json'), 'Owned checkpoint no longer matches')
            self.install()
        self.finish()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode',choices=['preflight','deploy','resume'])
    for name in ('bundle','sha256','commit','stage','job'):
        parser.add_argument('--' + name)
    args = parser.parse_args()
    driver = None
    try:
        require(os.name == 'posix' and os.getuid() == 0, 'Human-run ECS root only')
        os.umask(0o077)
        import fcntl
        with no_links('/run/lock/xiquan-stock-cutover.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.mode == 'preflight':
                preflight(args.bundle,args.sha256,args.commit)
            else:
                driver = Desktop049(args.stage,args.job if args.mode == 'resume' else None)
                require(driver.report['source_commit'] == args.commit, 'Explicit commit mismatch')
                getattr(driver,args.mode)()
    except Exception as error:
        message = str(error) if isinstance(error,DeploymentError) else type(error).__name__ + ': inspect private evidence'
        print('DESKTOP049_STOPPED: ' + message,file=sys.stderr)
        if driver and driver.job:
            print('PRIVATE_DESKTOP_JOB=' + str(driver.job),file=sys.stderr)
            print('FAILED_PHASE=' + getattr(driver,'last_phase','precheck'),file=sys.stderr)
        return 1
    finally:
        if driver:
            for restore in driver.restores:
                try:
                    restore.stop()
                except Exception:
                    pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
