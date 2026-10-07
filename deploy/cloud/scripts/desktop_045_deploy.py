"""Fresh human-run 0.4.5 cutover. No stock/reset replay, clearing or installer publication."""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from stock_deploy import Stock, check_resources, require
from operations_backup_verify import DeploymentError, run, wait_healthy, write_environment
from operations_preflight import stage_bundle, no_links, digest_file, protected_files, query_cloud_state
from operations_deploy import CLOUD, PROJECT, BACKUPS, MOUNT, json_read, json_write, require_single_api

OLD = '20261005_independent_stock'
HEAD = '20261007_desktop_ops'
TOOLS = ('desktop_045_deploy.py', 'desktop_045_guard.py', 'stock_deploy.py', 'stock_guard.py',
         'operations_backup_verify.py', 'operations_preflight.py', 'operations_deploy.py', 'operations_offline_build.py')


def fresh_state():
    state = query_cloud_state()
    require(state['pg_major'] == 17 and state['schema_revision'] == OLD and not state['pending_resets'] and
            not state['business_state']['maintenance'] and
            state['business_state']['policy_version'] == state['active_policy']['policy_version'],
            'Expected healthy direct predecessor, matching access policy and no pending reset/maintenance')
    return state


def preflight(bundle, digest, commit):
    identity = stage_bundle(bundle, digest)
    require(identity['source_commit'] == commit, 'Source commit mismatch')
    state = fresh_state()
    root = no_links('/opt/xiquan-releases')
    root.mkdir(mode=0o700, exist_ok=True)
    require(root.stat().st_uid == 0 and not root.stat().st_mode & 0o077, 'Private stage root required')
    stage = root / ('desktop045-stage-' + uuid.uuid4().hex)
    identity = stage_bundle(bundle, digest, stage)
    manifest = json_read(stage / 'xiquan/source-manifest.json')
    records = {row['file']: row for row in manifest['files']}
    require('server/migrations/versions/' + HEAD + '.py' in records, 'Reviewed additive migration missing')
    require(json_read(stage / 'xiquan/client/package.json')['version'] == '0.4.5', 'Wrong renderer version')
    for name in TOOLS:
        require(records['deploy/cloud/scripts/' + name]['sha256'] == digest_file(Path(__file__).parent / name),
                'Transport tool differs from exact committed SOURCE')
    json_write(stage / 'desktop-stage.json', dict(**identity, state=state, protected=protected_files(CLOUD)))
    print(json.dumps(dict(stage=str(stage), source_commit=commit, source_sha256=digest,
                          schema=state['schema_revision'], open_orders_preserved=state['open_visits'])))


class Desktop045(Stock):
    def __init__(self, stage, job=None):
        require(re.fullmatch('/opt/xiquan-releases/desktop045-stage-[0-9a-f]{32}', stage), 'Invalid exact stage path')
        self.stage = no_links(stage)
        self.source = self.stage / 'xiquan'
        self.manifest = json_read(self.source / 'source-manifest.json')
        self.report = json_read(self.stage / 'desktop-stage.json')
        require(self.report['source_commit'] == self.manifest['source_commit'], 'Stage identity changed')
        for row in self.manifest['files']:
            file = no_links(self.source / row['file'])
            require(file.stat().st_size == row['size'] and digest_file(file) == row['sha256'], 'Staged bytes changed')
        for name in TOOLS:
            require(digest_file(self.source / 'deploy/cloud/scripts' / name) == digest_file(Path(__file__).parent / name),
                    'Tool identity changed')
        if job:
            require(re.fullmatch('/opt/xiquan-backups/desktop045-cutover-[0-9a-f]{32}', job), 'Invalid exact recovery job')
        self.job = no_links(job) if job else None
        self.context = json_read(self.job / 'context.json') if job else {}
        self.restores = []
        self.api_stop_started = False
        self.resolve_environment()
        self.env.update(RUNTIME_DATABASE_URL=self.normal_env['RUNTIME_DATABASE_URL'],
                        RESET_DATABASE_URL=self.normal_env['RESET_DATABASE_URL'])

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
                   '--mount', 'type=bind,src=' + str(self.source / 'deploy/cloud/scripts/desktop_045_guard.py') + ',dst=/desktop_guard.py,readonly',
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

    def finish(self):
        self.protected()
        require(digest_file(CLOUD / '.env') == self.context['env_sha256'] and
                digest_file(CLOUD / 'docker-compose.prod.yml') == self.context['compose_sha256'], 'Private configuration changed')
        # Release ONLY this proven job before starting normal reset recovery.
        # No artificial worker pause/re-enable or repeated API restart is needed.
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
        print('DESKTOP045_API_WEB_DEPLOYED; desktop signed-channel publication and human acceptance remain.')

    def deploy(self):
        self.protected()
        fresh_state()
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
        check_resources('desktop045-before-offline-build')
        owner = str(uuid.uuid4())
        self.job = no_links(BACKUPS / ('desktop045-cutover-' + owner.replace('-','')))
        self.job.mkdir(mode=0o700)
        print('PRIVATE_DESKTOP_JOB=' + str(self.job), flush=True)
        self.context = dict(owner=owner,stage=str(self.stage),source_commit=self.report['source_commit'],network=private[0],
                            isolated_network='xiquan-desktop-proof-' + owner,postgres_image=info[1]['Image'],
                            env_sha256=digest_file(CLOUD / '.env'),compose_sha256=digest_file(CLOUD / 'docker-compose.prod.yml'),
                            tools={name:digest_file(Path(__file__).parent / name) for name in TOOLS})
        write_environment(self.job / 'maintenance.env', self.env)
        self.build(info[0]['Image'])
        json_write(self.job / 'context.json', self.context)
        run(['docker','network','create','--internal',self.context['isolated_network']])
        self.guard('inspect')
        check_resources('desktop045-before-backup', include_restore=True)
        self.phase('stop-api-writes')
        self.api_stop_started = True
        self.compose('stop','api')
        json_write(self.job / 'before.json', self.guard('claim'))
        clone = self.backup('before')
        clone_env = self.job / 'clone-migration.env'
        write_environment(clone_env, dict(self.env,DATABASE_URL=clone.database_url))
        json_write(self.job / 'clone-before.json', self.guard('inspect', clone_env, self.context['isolated_network']))
        self.guard('migrate', clone_env, self.context['isolated_network'], baseline='clone-before.json')
        clone.stop()
        require(self.guard('inspect') == json_read(self.job / 'before.json'), 'Production changed during isolated rehearsal')
        self.phase('additive-production-migration')
        json_write(self.job / 'after.json', self.guard('migrate', baseline='before.json'))
        self.backup('after').stop()
        json_write(self.job / 'ready.json', {'image_id':self.context['image_id'],'source_commit':self.report['source_commit']})
        self.install()
        self.finish()

    def resume(self):
        require(self.context['stage'] == str(self.stage) and self.context['source_commit'] == self.report['source_commit'] and
                self.context['tools'] == {name:digest_file(Path(__file__).parent / name) for name in TOOLS}, 'Recovery source/tool identity differs')
        require(not (self.job / 'completed.json').exists(), 'Already completed; do not redeploy')
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
                driver = Desktop045(args.stage,args.job if args.mode == 'resume' else None)
                require(driver.report['source_commit'] == args.commit, 'Explicit commit mismatch')
                getattr(driver,args.mode)()
    except Exception as error:
        message = str(error) if isinstance(error,DeploymentError) else 'Checkpoint stopped; inspect private evidence'
        print('DESKTOP045_STOPPED: ' + message,file=sys.stderr)
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
