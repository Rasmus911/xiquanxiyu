"""Explicit user-run October 4 cutover. No force-clear, cleanup or automatic rollback."""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qsl, quote

if os.name == 'posix':
    import fcntl

from operations_backup_verify import (DeploymentError, IsolatedRestore, inspect_database,
    run, verify_full_restore, wait_healthy, write_environment)
from operations_preflight import no_links, digest_file, protected_files, query_cloud_state

CLOUD = Path('/opt/xiquan/xiquan/deploy/cloud')
PROJECT = CLOUD.parents[1]
BACKUPS = Path('/opt/xiquan-backups')
MOUNT = '/var/lib/xiquan-operations'
EXPECTED_SCHEMA = '20261004_catalog_packages'

REHEARSAL_ROLE_CHECK = '''
import os
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DatabaseError
from app import create_app
from app.extensions import db
from app.deployment_checks import check_database_roles
from app.operations_upgrade import _require_owner
from app.business_barrier import BARRIER_KEY, exclusive_barrier
urls={kind:make_url(os.environ[key]) for kind,key in
      [('runtime','RUNTIME_DATABASE_URL'),('reset','RESET_DATABASE_URL'),('backup','RESET_BACKUP_DATABASE_URL')]}
if any(not url.host.startswith('xiquan-operations-restore-') or url.database!='operations_restore' for url in urls.values()):
    raise RuntimeError('Refuse a nonisolated role exercise')
check_database_roles(urls)
app=create_app()
with app.app_context():
    with db.engine.connect() as owner:
        _require_owner(owner)
        old_note=owner.exec_driver_sql("SELECT note FROM wristbands WHERE number='001'").scalar_one()
        owner.rollback()
        with exclusive_barrier(owner,'operations-clone-check'):
            owner.exec_driver_sql("UPDATE business_state SET maintenance=true,maintenance_reset_id='operations-clone-check' WHERE id=1")
            owner.commit()
    runtime=create_engine(urls['runtime'],hide_parameters=True)
    try:
        with runtime.connect() as connection:
            try: _require_owner(connection)
            except ValueError: pass
            else: raise RuntimeError('Runtime falsely passed actual owner check')
            connection.rollback()
            connection.exec_driver_sql("SELECT set_config('xiquan.reset_task_id','operations-clone-check',false)")
            connection.exec_driver_sql(f'SELECT pg_advisory_lock({BARRIER_KEY})')
            connection.commit()
            try:
                connection.exec_driver_sql("UPDATE wristbands SET note='forged-clone-write' WHERE number='001'")
            except DatabaseError: connection.rollback()
            else: raise RuntimeError('Forged maintenance write was not blocked')
            connection.exec_driver_sql(f'SELECT pg_advisory_unlock({BARRIER_KEY})')
            connection.commit()
        with db.engine.connect() as owner:
            if owner.exec_driver_sql("SELECT note FROM wristbands WHERE number='001'").scalar_one()!=old_note:
                raise RuntimeError('A forged runtime write changed the row')
            owner.rollback()
            with exclusive_barrier(owner,'operations-clone-check'):
                owner.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
                owner.commit()
    finally: runtime.dispose()
print('REHEARSAL_PG17_ROLE_LOCKS_OK')
'''


def json_read(path):
    return json.loads(no_links(path).read_text(encoding='utf-8-sig'))


def json_write(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as writer:
        json.dump(value, writer, ensure_ascii=False, indent=2)
        writer.flush(); os.fsync(writer.fileno())


def require_idle(state):
    if (state['pg_major'] != 17 or state['open_visits'] or state['unresolved_wristbands']
            or state['pending_resets'] or state['business_state']['maintenance']
            or state['business_state']['policy_version'] != state['active_policy']['policy_version']):
        raise DeploymentError('Unfinished wristbands/reset/maintenance blocks cutover; no bill was cleared')


def require_confirmation(job, digest):
    if (job.get('status') != 'preview_ready' or not re.fullmatch('[0-9a-f]{64}', digest)
            or job.get('preview_sha256') != digest):
        raise DeploymentError('Explicit confirmation must match this prepared preview')


def require_single_api(output):
    try:
        entries = [json.loads(line) for line in output.splitlines() if line.strip()]
        if len(entries) != 1 or not entries[0].get('ID'): raise ValueError
    except Exception:
        raise DeploymentError('Exactly one actual running API container is required') from None


def verify_retained_rows(before, after):
    allowed = {'business_state', 'catalog_items', 'wristbands', 'system_settings', 'audit_logs'}
    if set(before) != set(after) or any(before[name] != after[name] for name in before if name not in allowed):
        raise DeploymentError('A retained financial/history/account row changed; API remains stopped')


def verify_schema_data_preserved(before, after):
    if set(before) != set(after) or any(before[name] != after[name] for name in before if name != 'alembic_version'):
        raise DeploymentError('Schema migration changed an original business/account value; API remains stopped')


def validate_stage(stage):
    stage = no_links(stage)
    if not re.fullmatch('/opt/xiquan-releases/operations-stage-[0-9a-f]{32}', str(stage)):
        raise DeploymentError('Only the reviewed private stage is accepted')
    report = json_read(stage / 'preflight-report.json')
    manifest = json_read(stage / 'xiquan/source-manifest.json')
    if manifest['source_commit'] != report['source_commit'] or report['stage_directory'] != str(stage):
        raise DeploymentError('Staged source identity differs from preflight')
    seen = set()
    for row in manifest['files']:
        relative = row['file']
        from operations_preflight import safe_relative
        safe_relative(relative)
        if relative in seen: raise DeploymentError('Repeated source path')
        seen.add(relative)
        path = no_links(stage / 'xiquan' / relative)
        if path.stat().st_size != row['size'] or digest_file(path) != row['sha256']:
            raise DeploymentError('Staged source changed since upload')
    if not {'server/Dockerfile','server/app/operations_backup.py',
            'client/dist/index.html','mobile/dist/index.html'}.issubset(seen):
        raise DeploymentError('Required staged operational source is missing')
    return report, manifest


def prepare(operations):
    operations.initial_check()
    operations.stop_api()
    operations.idle_check()
    operations.legacy_backup_restore()
    operations.build_image()
    operations.rehearsal()
    operations.migrate()
    operations.snapshot_restore()
    preview = operations.preview()
    if not preview.get('can_apply'): raise DeploymentError('Business preview has conflicts; review private preview')
    operations.save_preview(preview)


def apply(operations, confirmation):
    operations.confirmation_check(confirmation)
    operations.recheck_receipt()
    operations.business_apply()
    operations.verify_business()
    operations.install_source()
    operations.start_api()
    operations.publish_web()
    operations.finish()


class Deployment:
    def __init__(self, stage, *, job=None):
        self.stage = Path(stage)
        self.report, self.manifest = validate_stage(self.stage)
        self.source = self.stage / 'xiquan'
        self.job = Path(job) if job else None
        self.initial = None
        self.context = json_read(self.job / 'context.json') if self.job else {}
        self.env = None

    def phase(self, name):
        print('DEPLOY_PHASE=' + name, flush=True)
        if self.job:
            json_write(self.job / ('phase-' + uuid.uuid4().hex + '.json'), {'phase': name})

    def compose(self, *args, override=None):
        command = ['docker','compose','--env-file',str(CLOUD / '.env'),'-p','xiquan',
            '-f',str(CLOUD / 'docker-compose.prod.yml')]
        if override: command += ['-f',str(override)]
        return run(command + list(args))

    def resolve_environment(self):
        config = json.loads(run(['docker','compose','--env-file',str(CLOUD / '.env'),'-p','xiquan',
            '-f',str(self.source / 'deploy/cloud/docker-compose.prod.yml'),
            '--profile','maintenance','config','--format','json']))
        maintenance = {k:str(v) for k,v in config['services']['maintenance']['environment'].items() if v is not None}
        normal = {k:str(v) for k,v in config['services']['api']['environment'].items() if v is not None}
        if 'MAINTENANCE_DATABASE_URL' in normal or normal['DATABASE_URL'] != normal['RUNTIME_DATABASE_URL']:
            raise DeploymentError('Owner credentials must not enter the normal API')
        values = [maintenance['DATABASE_URL'], normal['RUNTIME_DATABASE_URL'],
            normal['RESET_DATABASE_URL'], normal['RESET_BACKUP_DATABASE_URL']]
        urls = [urlsplit(value) for value in values]
        if (any(url.scheme != 'postgresql+psycopg' or not url.hostname or not url.username
                or not url.password or not url.path.strip('/') for url in urls)
                or len({(url.hostname,url.port or 5432,url.path) for url in urls}) != 1
                or len({url.username for url in urls}) != 4):
            raise DeploymentError('Four distinct private database logins on one database are required')
        if [url.username for url in urls[1:]] != ['xiquan_app','xiquan_reset','xiquan_backup']:
            raise DeploymentError('Use the existing dedicated runtime/reset/backup identities')
        maintenance.update(RESET_PRIVATE_DIR=MOUNT, MAINTENANCE_PROCESS='1', RESET_WORKER_ENABLED='0', SMS_ENABLED='0')
        self.env, self.normal_env = maintenance, normal

    def protected_check(self):
        if protected_files(CLOUD) != self.report['protected_references']:
            raise DeploymentError('Protected nginx/update/download references changed; stop and inspect')

    def initial_check(self):
        self.phase('read-only-final-check')
        self.protected_check()
        self.initial = query_cloud_state()
        require_idle(self.initial)
        if self.initial['schema_revision'] != '20261003_preserve_administrators':
            raise DeploymentError('Preparation requires the verified October 3 schema; do not repeat a migration')
        info = json.loads(run(['docker','inspect','xiquan-api-1','xiquan-postgres-1','xiquan-nginx-1']))
        if any(not item['State'].get('Running') or item['State'].get('Health',{}).get('Status') != 'healthy' for item in info):
            raise DeploymentError('All three current containers must be healthy')
        require_single_api(run(['docker','ps','--filter','label=com.docker.compose.project=xiquan',
            '--filter','label=com.docker.compose.service=api','--format','{{json .}}']))
        common = set(info[0]['NetworkSettings']['Networks']) & set(info[1]['NetworkSettings']['Networks'])
        networks = [network for network in common if json.loads(run(['docker','network','inspect',network]))[0]['Internal']]
        if len(networks) != 1: raise DeploymentError('One existing private database network is required')
        no_links(BACKUPS)
        if shutil.disk_usage(BACKUPS).free < 3 * 1024**3:
            raise DeploymentError('At least 3 GiB free private backup space is required')
        self.resolve_environment()
        running_env = dict(value.split('=',1) for value in info[0]['Config']['Env'] if '=' in value)
        if any(running_env.get(key,'') != self.normal_env.get(key,'') for key in
                ('SECRET_KEY','JWT_SECRET_KEY','AUDIT_HMAC_KEY','DATABASE_URL')):
            raise DeploymentError('Existing runtime/signing identities changed; no key or password rotation here')
        self.job = BACKUPS / ('operations-cutover-' + uuid.uuid4().hex)
        self.job.mkdir(mode=0o700)
        self.context = dict(stage=str(self.stage), source_commit=self.report['source_commit'],
            network=networks[0], postgres_image=info[1]['Image'], old_api_image=info[0]['Image'],
            new_image='xiquan-api:operations-' + self.report['source_commit'][:12])
        self.context['deployment_tools']={name:digest_file(Path(__file__).parent / name) for name in
            ('operations_deploy.py','operations_backup_verify.py','operations_preflight.py')}
        json_write(self.job / 'context.json', self.context)
        json_write(self.job / 'before-state.json', self.initial)
        shutil.copy2(CLOUD / '.env', self.job / 'before.env'); (self.job / 'before.env').chmod(0o600)
        shutil.copy2(CLOUD / 'docker-compose.prod.yml', self.job / 'before-compose.yml')
        (self.job / 'before-compose.yml').chmod(0o600)
        write_environment(self.job / 'maintenance.env', self.env)
        # Preserve the old image even after changing a generic image tag later.
        run(['docker','tag', self.context['old_api_image'], 'xiquan-api:rollback-' + self.job.name[-32:]])

    def stop_api(self):
        self.phase('stop-api-writes')
        self.compose('stop','api')
        if json.loads(run(['docker','inspect','xiquan-api-1']))[0]['State']['Running']:
            raise DeploymentError('API is still running; no backup or migration may start')

    def idle_check(self):
        require_idle(query_cloud_state())
        self.protected_check()

    def legacy_backup_restore(self):
        self.phase('pre-migration-actual-pg17-restore')
        before = inspect_database('xiquan-postgres-1')
        json_write(self.job / 'pre-migration-original-columns.json',inspect_database('xiquan-postgres-1',legacy_projection=True))
        backup_url = urlsplit(self.env['RESET_BACKUP_DATABASE_URL'])
        settings = dict(PGHOST=backup_url.hostname, PGPORT=str(backup_url.port or 5432),
            PGDATABASE=unquote(backup_url.path.strip('/')), PGUSER=unquote(backup_url.username),
            PGPASSWORD=unquote(backup_url.password), PGOPTIONS='-c default_transaction_read_only=on')
        for key,value in parse_qsl(backup_url.query):
            if key not in ('sslmode','sslrootcert','sslcert','sslkey'):
                raise DeploymentError('Unsupported private backup connection option')
            settings['PG' + key.upper()] = value
        file = self.job / 'pre-migration.backup'
        envfile = self.job / 'dump.env'
        write_environment(envfile, settings)
        run(['docker','run','--rm','--user','0:0','--network',self.context['network'],
            '--env-file',str(envfile),'--mount','type=bind,src=' + str(self.job) + ',dst=' + MOUNT,
            '--entrypoint','pg_dump',self.context['postgres_image'],'--format=custom',
            '--no-owner','--no-acl','--no-password','--file',MOUNT + '/' + file.name])
        no_links(file).chmod(0o600)
        restore = IsolatedRestore(self.job, self.context['postgres_image'], self.context['network'])
        restore.start(); restore.restore(file)
        verified = inspect_database(restore.name)
        verify_full_restore(before, verified)
        if inspect_database('xiquan-postgres-1') != before:
            raise DeploymentError('Source changed while stopped; no migration authorized')
        json_write(self.job / 'pre-migration-verified.json', dict(source=before, restored=verified,
            dump_sha256=digest_file(file), dump_size=file.stat().st_size,
            restore_container=restore.name, restore_volume=restore.volume))
        self.pre_restore = restore

    def build_image(self):
        self.phase('build-new-api-image')
        run(['docker','build','--tag',self.context['new_image'],str(self.source / 'server')], timeout=3600)

    def rehearsal(self):
        self.phase('isolated-new-schema-business-and-pg17-role-rehearsal')
        restore = self.pre_restore
        before = inspect_database(restore.name)
        if before['server']['system_identifier'] == inspect_database('xiquan-postgres-1')['server']['system_identifier']:
            raise DeploymentError('Rehearsal must not connect to the production cluster')
        passwords = {role:secrets.token_urlsafe(48) for role in ('xiquan_app','xiquan_reset','xiquan_backup')}
        for filename in ('runtime-role.sql','reset-role.sql','backup-role.sql'):
            run(['docker','exec','-i',restore.name,'psql','-X','-q','-v','ON_ERROR_STOP=1',
                '-U','operations_restore','-d','operations_restore'],
                input_file=self.source / 'deploy/cloud/scripts' / filename)
        sqlfile = self.job / 'isolated-role-login.sql'
        with sqlfile.open('x',encoding='utf-8') as writer:
            sqlfile.chmod(0o600)
            for role,password in passwords.items():
                writer.write(f"ALTER ROLE {role} LOGIN PASSWORD '{password}';\n")
        run(['docker','exec','-i',restore.name,'psql','-X','-q','-v','ON_ERROR_STOP=1',
             '-U','operations_restore','-d','operations_restore'],input_file=sqlfile)
        url=lambda role:'postgresql+psycopg://' + role + ':' + quote(passwords[role],safe='') + '@' + restore.name + ':5432/operations_restore'
        env=dict(self.env,DATABASE_URL=restore.database_url,RESET_BACKUP_DATABASE_URL=url('xiquan_backup'),
            RUNTIME_DATABASE_URL=url('xiquan_app'),RESET_DATABASE_URL=url('xiquan_reset'))
        envfile=self.job / 'rehearsal.env'; write_environment(envfile,env)
        self.maintenance(['db','upgrade'],environment=envfile)
        verify_schema_data_preserved(json_read(self.job / 'pre-migration-original-columns.json')['tables'],
            inspect_database(restore.name,legacy_projection=True)['tables'])
        directory=self.job / 'rehearsal'; directory.mkdir(mode=0o700)
        self.maintenance(['operations-backup','create','--output',MOUNT + '/rehearsal'],environment=envfile)
        second=IsolatedRestore(self.job,self.context['postgres_image'],self.context['network'])
        second.start(); second.restore(directory / 'database.backup')
        verifyenv=self.job / 'rehearsal-verify.env'
        write_environment(verifyenv,dict(env,XIQUAN_RESTORE_DATABASE_URL=second.database_url))
        self.maintenance(['operations-backup','verify-restored','--database-url-env','XIQUAN_RESTORE_DATABASE_URL',
            '--receipt',MOUNT + '/rehearsal/candidate.json'],environment=verifyenv)
        preview=json.loads(self.maintenance(['operations-upgrade','preview','--output',MOUNT + '/rehearsal/preview.json'],environment=envfile))
        if not preview['can_apply']: raise DeploymentError('Isolated rehearsal preview is blocked')
        self.maintenance(['operations-upgrade','apply','--preview-sha256',preview['preview_sha256'],
            '--backup-receipt',MOUNT + '/rehearsal/receipt.json','--confirm','operations-20261004'],environment=envfile)
        result=json.loads(self.maintenance(['operations-upgrade','verify'],environment=envfile))
        if not result['valid'] or result['maintenance']: raise DeploymentError('Isolated business rehearsal failed')
        if self.maintenance(['-c',REHEARSAL_ROLE_CHECK],environment=envfile,python=True) != 'REHEARSAL_PG17_ROLE_LOCKS_OK':
            raise DeploymentError('Actual isolated PG17 ownership/grants/forged-lock test failed')
        if inspect_database('xiquan-postgres-1') != json_read(self.job / 'pre-migration-verified.json')['source']:
            raise DeploymentError('Production changed during isolated rehearsal; no migration authorized')
        json_write(self.job / 'rehearsal-verified.json',dict(pg_major=17,isolated_server_id=before['server']['system_identifier'],
            actual_migration=True,actual_restore=True,actual_apply=True,role_and_lock_exercise=True,
            active_wristbands=100,formal_items=42,production_unchanged=True))
        second.stop(); restore.stop()

    def maintenance(self, arguments, *, environment=None, python=False):
        return run(['docker','run','--rm','--user','0:0','--network',self.context['network'],
            '--env-file',str(environment or self.job / 'maintenance.env'),
            '--mount','type=bind,src=' + str(self.job) + ',dst=' + MOUNT,
            '--entrypoint','python' if python else 'flask',self.context['new_image']]
            + (arguments if python else ['--app','run.py'] + arguments))

    def migrate(self):
        self.phase('explicit-owner-schema-migration')
        # Own URL and schema ownership are checked by the snapshot CLI before DDL.
        directory = self.job / 'owner-check'; directory.mkdir(mode=0o700)
        self.maintenance(['operations-backup','create','--output',MOUNT + '/owner-check'])
        self.maintenance(['db','upgrade'])
        if query_cloud_state()['schema_revision'] != EXPECTED_SCHEMA:
            raise DeploymentError('Migration did not reach the expected schema')
        verify_schema_data_preserved(json_read(self.job / 'pre-migration-original-columns.json')['tables'],
            inspect_database('xiquan-postgres-1',legacy_projection=True)['tables'])

    def snapshot_restore(self):
        self.phase('post-migration-snapshot-and-full-restore')
        directory = self.job / 'post-migration'; directory.mkdir(mode=0o700)
        self.maintenance(['operations-backup','create','--output',MOUNT + '/post-migration'])
        restore = IsolatedRestore(self.job, self.context['postgres_image'], self.context['network'])
        restore.start(); restore.restore(directory / 'database.backup')
        environment = dict(self.env, XIQUAN_RESTORE_DATABASE_URL=restore.database_url)
        write_environment(self.job / 'restore.env', environment)
        self.maintenance(['operations-backup','verify-restored','--database-url-env','XIQUAN_RESTORE_DATABASE_URL',
            '--receipt',MOUNT + '/post-migration/candidate.json'], environment=self.job / 'restore.env')
        receipt = json_read(directory / 'receipt.json')
        if receipt['restore']['status'] != 'verified': raise DeploymentError('No verified post-migration receipt')
        restore.stop()

    def preview(self):
        self.phase('private-business-preview')
        return json.loads(self.maintenance(['operations-upgrade','preview','--output',MOUNT + '/preview.json']))

    def save_preview(self, preview):
        record = dict(status='preview_ready', preview_sha256=preview['preview_sha256'],
            stage=str(self.stage), source_commit=self.report['source_commit'])
        json_write(self.job / 'prepared.json', record)
        print('DEPLOY_PREVIEW_READY_JSON=' + json.dumps(dict(job_path=str(self.job), **record,
            active_wristbands=100, formal_items=42, retained_money_and_history=True)), flush=True)

    def confirmation_check(self, confirmation):
        self.phase('check-explicit-preview-confirmation')
        require_confirmation(json_read(self.job / 'prepared.json'), confirmation)
        self.confirmed = confirmation
        if self.context['stage'] != str(self.stage) or self.context['source_commit'] != self.report['source_commit']:
            raise DeploymentError('Prepared attempt belongs to different staged source')
        if self.context.get('deployment_tools') != {name:digest_file(Path(__file__).parent / name) for name in
                ('operations_deploy.py','operations_backup_verify.py','operations_preflight.py')}:
            raise DeploymentError('Deployment tools changed since preparation; do not apply a different revision')
        self.protected_check()
        if json.loads(run(['docker','inspect','xiquan-api-1']))[0]['State']['Running']:
            raise DeploymentError('API must remain stopped during confirmation')
        require_idle(query_cloud_state())
        self.resolve_environment()

    def recheck_receipt(self):
        self.phase('recheck-complete-snapshot-evidence')
        candidate = json_read(self.job / 'post-migration/candidate.json')
        self.baseline = candidate['checks']
        self.inspect_current('pre-apply-checks.json')
        if json_read(self.job / 'pre-apply-checks.json') != self.baseline:
            raise DeploymentError('Database changed after backup or preview; refuse to apply')
        receipt = json_read(self.job / 'post-migration/receipt.json')
        if (receipt['restore']['status'] != 'verified' or receipt['restore']['pg_major'] != 17
                or receipt['dump_sha256'] != digest_file(self.job / 'post-migration/database.backup')
                or receipt['restore']['source_server_id'] == receipt['restore']['restored_server_id']):
            raise DeploymentError('Private post-migration restore evidence is invalid')

    def inspect_current(self, name):
        code = "from app import create_app; from app.extensions import db; from app.operations_backup import collect_snapshot_checks,_postgres_snapshot_begin,write_private_json; from app.operations_upgrade import maintenance_connection; "
        code += "from pathlib import Path; app=create_app();\nwith app.app_context(), maintenance_connection() as c:\n _postgres_snapshot_begin(c); checks=collect_snapshot_checks(c); write_private_json(Path('" + MOUNT + '/' + name + "'),checks); c.rollback()"
        self.maintenance(['-c',code], python=True)

    def business_apply(self):
        self.phase('apply-approved-formal-catalog-and-wristbands')
        self.maintenance(['operations-upgrade','apply','--preview-sha256',self.confirmed,
            '--backup-receipt',MOUNT + '/post-migration/receipt.json','--confirm','operations-20261004'])

    def verify_business(self):
        self.phase('verify-preserved-money-inventory-accounts-and-audit')
        result = json.loads(self.maintenance(['operations-upgrade','verify']))
        if not result['valid'] or result['maintenance']:
            raise DeploymentError('Operational catalog verification failed')
        self.inspect_current('after-apply-checks.json')
        after = json_read(self.job / 'after-apply-checks.json')
        verify_retained_rows(self.baseline['tables'], after['tables'])
        if self.baseline['totals'] != after['totals'] or not after['audit_valid']:
            raise DeploymentError('Retained totals or audit verification failed')
        before_state = json_read(self.job / 'before-state.json')
        state = query_cloud_state()
        if (state['active_policy'] != before_state['active_policy'] or
                sorted(state['administrators'],key=lambda row:row['id']) !=
                sorted(before_state['administrators'],key=lambda row:row['id'])):
            raise DeploymentError('Existing administrator identities or bindings changed')
        preview = json_read(self.job / 'preview.json')
        # Individual inventory quantities, not merely a coincidentally equal sum.
        inventory = self.maintenance(['-c',"from app import create_app; from app.extensions import db; import json; app=create_app();\nwith app.app_context():\n rows=db.session.execute(db.text(\"SELECT id,stock_quantity FROM catalog_items WHERE kind='product'\")).all(); print(json.dumps({r[0]:str(r[1]) for r in rows}))"], python=True)
        current_stock = json.loads(inventory)
        if any(current_stock.get(key) != value['stock_quantity'] for key,value in preview['retained_products'].items()):
            raise DeploymentError('An individual existing product stock quantity changed')
        self.protected_check()
        json_write(self.job / 'business-verified.json', dict(valid=True, active_wristbands=100, formal_items=42,
            rows_preserved=True, totals_preserved=True, audit_valid=True, administrator_bindings_preserved=True))

    def install_source(self):
        self.phase('preserve-and-install-reviewed-source')
        rollback = self.job / 'old-files'; rollback.mkdir(mode=0o700)
        for record in self.manifest['files']:
            relative = record['file']
            if not (relative.startswith('server/') or relative == 'deploy/cloud/docker-compose.prod.yml'): continue
            original = no_links(self.source / relative)
            target = no_links(PROJECT / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = rollback / relative; backup.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                shutil.copy2(target,backup); backup.chmod(0o600)
            replacement = target.with_name(target.name + '.operations-' + uuid.uuid4().hex)
            shutil.copyfile(original, replacement); replacement.chmod(0o644)
            os.replace(replacement,target)
        run(['docker','tag',self.context['new_image'],'xiquan-api:owner-reset'])

    def start_api(self):
        self.phase('start-one-new-api-and-check-health')
        self.protected_check()
        override = self.job / 'compose-api-image.json'
        json_write(override, {'services': {'api': {'image': self.context['new_image']}}})
        self.compose('up','-d','--no-deps','--no-build','api',override=override)
        try: wait_healthy('xiquan-api-1', timeout=180)
        except DeploymentError:
            self.compose('stop','api')
            raise
        current = json.loads(run(['docker','inspect','xiquan-api-1']))[0]
        expected = json.loads(run(['docker','image','inspect',self.context['new_image']]))[0]['Id']
        if current['Image'] != expected: raise DeploymentError('Running API image differs from the staged build')

    def publish_web(self):
        self.phase('publish-web-and-mobile-web-without-touching-installers')
        for area,destination in [('client',CLOUD / 'web'),('mobile',CLOUD / 'mobile')]:
            no_links(destination).mkdir(exist_ok=True)
            records = [record for record in self.manifest['files'] if record['file'].startswith(area + '/dist/')]
            records.sort(key=lambda row: row['file'].endswith('/index.html'))
            for record in records:
                relative = record['file'].split('/dist/',1)[1]
                if relative == 'download-config.json' or relative.startswith('downloads/'):
                    raise DeploymentError('Web assets may not replace published APK metadata')
                target = no_links(destination / relative); target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    rollback = self.job / 'old-files' / 'deploy/cloud' / destination.name / relative
                    rollback.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
                    shutil.copy2(target,rollback); rollback.chmod(0o600)
                replacement = target.with_name(target.name + '.operations-' + uuid.uuid4().hex)
                shutil.copyfile(self.source / record['file'],replacement); replacement.chmod(0o644)
                os.replace(replacement,target)
        self.protected_check()
        run(['docker','exec','xiquan-nginx-1','nginx','-t'],timeout=30)
        run(['docker','exec','xiquan-nginx-1','nginx','-s','reload'],timeout=30)
        body = json.loads(run(['curl','--fail','--silent','--show-error','--max-time','20',
            'https://api.pqxqxy.xyz/api/health'],timeout=30))
        if not body.get('success') or body.get('data',{}).get('database') != 'ok':
            raise DeploymentError('Public API health check did not pass')

    def finish(self):
        self.phase('completed-cloud-cutover')
        self.protected_check()
        json_write(self.job / 'completed.json', dict(status='cloud_deployed', source_commit=self.report['source_commit'],
            active_wristbands=100, formal_items=42, financial_rows_preserved=True,
            installer_publication=False, cleanup_performed=False, real_device_checks_pending=True))
        print('OPERATIONS_CLOUD_DEPLOYED_OK', flush=True)
        print('PRIVATE_RECOVERY_DIRECTORY=' + str(self.job), flush=True)
        print('Web/API deployed. Existing installers, update feeds and all backups retained. Device acceptance remains required.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage',required=True)
    parser.add_argument('--mode',choices=['prepare','apply'],required=True)
    parser.add_argument('--job')
    parser.add_argument('--preview-sha256')
    args = parser.parse_args()
    deployment = None
    try:
        if os.name != 'posix' or os.getuid() != 0: raise DeploymentError('Run only as root on the existing ECS')
        if args.mode == 'apply' and (not args.job or not args.preview_sha256):
            raise DeploymentError('Apply requires an actual prepared job and preview confirmation')
        if args.job:
            path = no_links(args.job)
            if not re.fullmatch('/opt/xiquan-backups/operations-cutover-[0-9a-f]{32}',str(path)):
                raise DeploymentError('Only this tool private recovery directory is accepted')
            if path.stat().st_uid != 0 or stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise DeploymentError('Private recovery directory has unsafe ownership or permissions')
        lock = no_links('/run/lock/xiquan-operations-cutover.lock')
        with lock.open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
            deployment = Deployment(args.stage,job=args.job)
            if args.mode == 'prepare': prepare(deployment)
            else: apply(deployment,args.preview_sha256)
    except Exception as error:
        message = str(error) if isinstance(error,DeploymentError) else 'Cutover stopped; no automatic rollback or deletion'
        print('DEPLOY_STOPPED: ' + message,file=sys.stderr)
        if deployment and deployment.job: print('PRIVATE_RECOVERY_DIRECTORY=' + str(deployment.job),file=sys.stderr)
        print('Do not start an old API against a migrated schema or restore a dump blindly. All evidence is retained.',file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
