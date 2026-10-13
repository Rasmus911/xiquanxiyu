"""Human-run 0.5.0 cutover, exact checkpoints and isolated PostgreSQL proof."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from desktop_049_deploy import Desktop049
from stock_deploy import Stock, Restore
from operations_backup_verify import DeploymentError,run,wait_healthy,write_environment
from operations_preflight import stage_bundle,no_links,digest_file,protected_files,query_cloud_state
from operations_deploy import CLOUD,PROJECT,BACKUPS,MOUNT,json_read,json_write,require_single_api

OLD='20261008_registration_token'
HEAD='20261011_service_receipts'
TOOLS=('desktop_050_deploy.py','desktop_050_guard.py','desktop_049_deploy.py','desktop_049_guard.py',
       'stock_deploy.py','stock_guard.py','operations_backup_verify.py','operations_preflight.py',
       'operations_deploy.py','operations_offline_build.py')
MIB=1024**2


def require(value,message):
    if not value: raise DeploymentError(message)


def replace_context(path,value,expected_sha256):
    """Context is mutable; each prior exact version stays as private evidence."""
    path=no_links(path)
    require(digest_file(path)==expected_sha256,'Context changed outside this owned checkpoint')
    if json_read(path)==value: return expected_sha256
    previous=path.with_name('context-retained-'+uuid.uuid4().hex+'.json')
    with previous.open('xb') as writer:
        writer.write(path.read_bytes());writer.flush();os.fsync(writer.fileno())
    previous.chmod(0o600)
    temporary=path.with_name('context-next-'+uuid.uuid4().hex+'.json')
    json_write(temporary,value)
    require(digest_file(path)==expected_sha256,'Context changed before atomic replacement')
    os.replace(temporary,path)
    return digest_file(path)


def resource_budget(available,disk,*,restore=False):
    limit=256 if restore else 384
    required=limit+128+(256 if restore else 0)
    require(disk>=6*1024**3,'Need 6 GiB free backup disk; no cleanup performed')
    require(available>=required*MIB,f'Available memory={available//MIB} MiB; concurrent required={required} MiB')
    return dict(available_memory_mib=available//MIB,required_memory_mib=required,
                maintenance_limit_mib=limit,restore_limit_mib=256,reserve_mib=128,backup_free_mib=disk//MIB)


def check_resources(phase,*,restore=False):
    match=re.search(r'^MemAvailable:\s+(\d+)\s+kB',Path('/proc/meminfo').read_text(),re.M)
    require(match is not None,'Cannot measure memory')
    print('DESKTOP050_RESOURCES='+json.dumps(dict(phase=phase,**resource_budget(
        int(match[1])*1024,shutil.disk_usage(BACKUPS).free,restore=restore))),flush=True)


def retain_partial_backup(folder):
    folder=Path(folder)
    require(folder.is_dir() and not folder.is_symlink(),'Exact partial snapshot required')
    require(not(folder/'receipt.json').exists(),'Completed backup cannot be renamed')
    retained=folder.with_name(folder.name+'-retained-'+uuid.uuid4().hex)
    folder.rename(retained)
    return retained


def verify_source(source):
    manifest=json_read(source/'source-manifest.json')
    records={r['file']:r for r in manifest['files']}
    require(len(records)==len(manifest['files']),'Duplicate SOURCE records')
    from operations_preflight import safe_relative
    for row in manifest['files']:
        safe_relative(row['file']);file=no_links(source/row['file'])
        require(file.stat().st_size==row['size'] and digest_file(file)==row['sha256'],'Exact SOURCE changed')
    require(json_read(source/'client/package.json')['version']=='0.5.0','Wrong desktop version')
    require(json_read(source/'mobile/version.json')['version']=='1.2.9','Preserve mobile 1.2.9; no APK upgrade in this release')
    for relative in ('server/app/employee_identity.py','server/app/receipt_cleanup_worker.py',
                     'server/migrations/versions/20261011_employee_identity.py',
                     'server/migrations/versions/'+HEAD+'.py'):
        require(relative in records,'Reviewed 0.5.0 source missing')
    for name in TOOLS:
        require('deploy/cloud/scripts/'+name in records and
            digest_file(source/'deploy/cloud/scripts'/name)==digest_file(Path(__file__).parent/name),
            'Transport differs from committed SOURCE: '+name)
    return manifest


def fresh_state():
    state=query_cloud_state()
    require(state['pg_major']==17 and state['schema_revision']==OLD and not state['pending_resets'] and
        not state['business_state']['maintenance'] and
        state['business_state']['policy_version']==state['active_policy']['policy_version'],
        'Require PG17, exact 0.4.9 predecessor, consistent policy and no pending maintenance/reset')
    return state


def preflight(bundle,digest,commit):
    identity=stage_bundle(bundle,digest);require(identity['source_commit']==commit,'SOURCE commit mismatch')
    state=fresh_state();root=no_links('/opt/xiquan-releases');root.mkdir(mode=0o700,exist_ok=True)
    require(root.stat().st_uid==0 and not root.stat().st_mode&0o077,'Private stage root required')
    stage=root/('desktop050-stage-'+uuid.uuid4().hex)
    identity=stage_bundle(bundle,digest,stage);verify_source(stage/'xiquan')
    json_write(stage/'desktop-stage.json',dict(**identity,state=state,protected=protected_files(CLOUD)))
    print(json.dumps(dict(stage=str(stage),source_commit=commit,source_sha256=digest,
                          schema=state['schema_revision'],open_orders_preserved=state['open_visits'])))


class Desktop050(Desktop049):
    """Reuse byte-copy/PG restore mechanics, not predecessor/version decisions."""
    def __init__(self,stage,job=None):
        require(re.fullmatch('/opt/xiquan-releases/desktop050-stage-[0-9a-f]{32}',stage),'Exact 0.5.0 stage required')
        self.stage=no_links(stage);self.source=self.stage/'xiquan';self.manifest=verify_source(self.source)
        self.report=json_read(self.stage/'desktop-stage.json')
        require(self.report['source_commit']==self.manifest['source_commit'],'Stage identity changed')
        if job: require(re.fullmatch('/opt/xiquan-backups/desktop050-cutover-[0-9a-f]{32}',job),'Exact 0.5.0 checkpoint required')
        self.job=no_links(job) if job else None
        for folder in (self.stage,self.job):
            if folder: require(folder.stat().st_uid==0 and not folder.stat().st_mode&0o077,'Private root-owned directory required')
        self.context=json_read(self.job/'context.json') if job else {}
        self.context_file_sha256=digest_file(self.job/'context.json') if job else None
        self.restores=[];self.api_stop_started=False;self.resolve_environment()
        self.env.update(RUNTIME_DATABASE_URL=self.normal_env['RUNTIME_DATABASE_URL'],
                        RESET_DATABASE_URL=self.normal_env['RESET_DATABASE_URL'])

    def validate_compose_change(self):
        configs=[]
        for file in (CLOUD/'docker-compose.prod.yml',self.source/'deploy/cloud/docker-compose.prod.yml'):
            config=json.loads(run(['docker','compose','--env-file',str(CLOUD/'.env'),'-p','xiquan',
                '-f',str(file),'--profile','maintenance','config','--format','json']))
            config['services']['api'].pop('build',None)
            worker=config['services'].pop('receipt-cleanup',None)
            if file==self.source/'deploy/cloud/docker-compose.prod.yml':
                require(worker and not worker.get('ports') and not worker.get('expose') and
                    set(worker['networks'])=={'backend'} and worker['entrypoint']==['python','-m','app.receipt_cleanup_worker'] and
                    worker['environment']['DATABASE_URL']==self.env['DATABASE_URL'] and
                    worker['environment']['MAINTENANCE_DATABASE_URL']==self.env['DATABASE_URL'],
                    'Cleanup must be private, owner-only and have no HTTP ports')
            for service in config['services'].values():
                for mount in service.get('volumes',[]):
                    try: relative=Path(mount.get('source','')).relative_to(self.source)
                    except ValueError: continue
                    mount['source']=str(PROJECT/relative)
            configs.append(config)
        require(configs[0]==configs[1],'Compose changed beyond the private receipt task')

    def command(self,args,environment=None,network=None,extra_network=None):
        networks=['--network',network or self.context['network']]
        if extra_network: networks+=['--network',extra_network]
        argv=['docker','run','--rm','--user','0:0','--memory','256m','--memory-swap','256m','--cpus','1',
            '--pids-limit','128','--env','PYTHONPATH=/app:/',*networks,
            '--env-file',str(environment or self.job/'maintenance.env'),
            '--mount','type=bind,src='+str(self.job)+',dst='+MOUNT]
        for source,target in [('desktop_050_guard.py','desktop_guard.py'),('desktop_049_guard.py','desktop_049_guard.py'),('stock_guard.py','stock_guard.py')]:
            argv+=['--mount','type=bind,src='+str(self.source/'deploy/cloud/scripts'/source)+',dst=/'+target+',readonly']
        argv+=['--entrypoint','python',self.context['image_id'],*args]
        result=subprocess.run(argv,capture_output=True,text=True,timeout=900)
        if result.returncode:
            evidence=self.job/('command-failure-'+uuid.uuid4().hex+'.json')
            json_write(evidence,dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
            raise DeploymentError('Owner command failed; private evidence='+str(evidence))
        return result.stdout.strip()

    def restore(self,dump):
        require(not any(item.started for item in self.restores),'Prior restore must stop first')
        check_resources('isolated-restore',restore=True)
        restore=Restore(self.job,self.context['postgres_image'],self.context['isolated_network'])
        self.restores.append(restore);restore.start();restore.restore(dump);return restore

    def install(self):
        Stock.install(self)
        record=next(r for r in self.manifest['files'] if r['file']=='deploy/cloud/docker-compose.prod.yml')
        if digest_file(CLOUD/'docker-compose.prod.yml')!=record['sha256']:
            self.copy(record,CLOUD/'docker-compose.prod.yml',0o600)
        self.context['compose_sha256']=digest_file(CLOUD/'docker-compose.prod.yml')
        self.store_context()

    def store_context(self):
        self.context_file_sha256=replace_context(self.job/'context.json',self.context,self.context_file_sha256)

    def origin(self,route,output=None):
        argv=['curl','--http1.1','--fail','--silent','--show-error','--max-time','20',
              '--resolve','api.pqxqxy.xyz:443:127.0.0.1']
        if output: argv+=['--output',str(output)]
        return run(argv+['https://api.pqxqxy.xyz/'+route],timeout=30)

    def verify_api(self,worker):
        wait_healthy('xiquan-api-1',timeout=180)
        api=json.loads(run(['docker','inspect','xiquan-api-1']))[0]
        env=dict(v.split('=',1) for v in api['Config']['Env'] if '=' in v)
        require(api['Image']==self.context['image_id'] and env.get('RESET_WORKER_ENABLED')==worker and
            all(env.get(k,'')==self.normal_env.get(k,'') for k in
                ('DATABASE_URL','SECRET_KEY','JWT_SECRET_KEY','AUDIT_HMAC_KEY','REGISTRATION_TOKEN_SECRET')) and
            all(env.get(k,'0')=='0' for k in ('AUTO_CREATE_DB','RUN_MIGRATIONS','SEED_DEFAULTS')) and
            'MAINTENANCE_DATABASE_URL' not in env,'API identity/config differs')
        require_single_api(run(['docker','ps','--filter','label=com.docker.compose.project=xiquan',
            '--filter','label=com.docker.compose.service=api','--format','{{json .}}']))
        run(['docker','exec','xiquan-nginx-1','nginx','-t'])
        run(['docker','exec','xiquan-nginx-1','nginx','-s','reload'])
        require(json.loads(self.origin('api/health')).get('success'),'Origin health failed')

    def finish(self):
        self.protected()
        require(digest_file(CLOUD/'.env')==self.context['env_sha256'] and
                digest_file(CLOUD/'docker-compose.prod.yml')==self.context['compose_sha256'],'Private settings changed')
        released=self.job/'maintenance-released.json'
        if not released.exists():
            require(self.guard('inspect')==json_read(self.job/'after.json'),'Owned checkpoint changed before API switch')
            self.phase('start-exact-api-under-owned-maintenance')
            paused=self.job/('paused-'+uuid.uuid4().hex+'.json')
            json_write(paused,dict(services=dict(api=dict(image=self.context['image_id'],environment=dict(RESET_WORKER_ENABLED='0')))))
            self.compose('up','-d','--no-deps','--no-build','api',override=paused);self.verify_api('0')
            self.phase('release-only-owned-maintenance')
            json_write(released,self.guard('release',baseline='after.json'))
        else:
            state=query_cloud_state()
            require(state['schema_revision']==HEAD and not state['business_state']['maintenance'] and not state['pending_resets'],
                    'Final checkpoint has another maintenance/reset')
        self.phase('restore-normal-api-worker')
        override=self.job/('normal-'+uuid.uuid4().hex+'.json')
        json_write(override,dict(services={'api':dict(image=self.context['image_id'],environment=dict(RESET_WORKER_ENABLED='1')),
                                         'receipt-cleanup':dict(image=self.context['image_id'])}))
        self.compose('up','-d','--no-deps','--no-build','api',override=override);self.verify_api('1')
        for relative,route in [('client/dist/index.html','app/index.html'),('mobile/dist/index.html','mobile/index.html')]:
            output=self.job/('public-'+uuid.uuid4().hex);self.origin(route,output)
            require(digest_file(output)==digest_file(self.source/relative),'Origin renderer bytes differ')
        self.protected()
        self.phase('start-private-daily-receipt-cleanup')
        self.compose('up','-d','--no-deps','--no-build','receipt-cleanup',override=override)
        wait_healthy('xiquan-receipt-cleanup-1',timeout=180)
        json_write(self.job/'completed.json',dict(source_commit=self.report['source_commit'],
            source_sha256=self.report['bundle_sha256'],image_id=self.context['image_id'],schema=HEAD,
            desktop_version='0.5.0',receipt_cleanup=True,installer_publication=False))
        print('DESKTOP050_API_WEB_VERIFIED; signed installer publication remains.')

    def deploy(self):
        self.protected();fresh_state();self.validate_compose_change()
        info=json.loads(run(['docker','inspect','xiquan-api-1','xiquan-postgres-1']))
        require(all(r['State']['Running'] and r['State'].get('Health',{}).get('Status')=='healthy' for r in info),'Existing API/PG must be healthy')
        env=dict(v.split('=',1) for v in info[0]['Config']['Env'] if '=' in v)
        require(all(env.get(k,'')==self.normal_env.get(k,'') for k in
                    ('DATABASE_URL','SECRET_KEY','JWT_SECRET_KEY','AUDIT_HMAC_KEY','REGISTRATION_TOKEN_SECRET')),'Original runtime settings differ')
        private=[n for n in set(info[0]['NetworkSettings']['Networks'])&set(info[1]['NetworkSettings']['Networks'])
                 if json.loads(run(['docker','network','inspect',n]))[0]['Internal']]
        require(len(private)==1,'One private backend network required');check_resources('before-build')
        owner=str(uuid.uuid4());self.job=no_links(BACKUPS/('desktop050-cutover-'+owner.replace('-','')))
        self.job.mkdir(mode=0o700);print('PRIVATE_DESKTOP_JOB='+str(self.job),flush=True)
        self.context=dict(owner=owner,stage=str(self.stage),source_commit=self.report['source_commit'],
            network=private[0],isolated_network='xiquan-desktop-proof-'+owner,postgres_image=info[1]['Image'],
            env_sha256=digest_file(CLOUD/'.env'),compose_sha256=digest_file(CLOUD/'docker-compose.prod.yml'),
            tools={name:digest_file(Path(__file__).parent/name) for name in TOOLS})
        write_environment(self.job/'maintenance.env',self.env)
        self.build(info[0]['Image']);json_write(self.job/'context.json',self.context)
        self.context_file_sha256=digest_file(self.job/'context.json')
        run(['docker','network','create','--internal',self.context['isolated_network']])
        self.pre_stop_snapshot=self.guard('inspect')
        # Stop any prior private cleanup task before taking the exact financial snapshot.
        workers=run(['docker','ps','-a','--filter','label=com.docker.compose.project=xiquan',
            '--filter','label=com.docker.compose.service=receipt-cleanup','--format','{{.ID}}'])
        if workers:
            for container in workers.splitlines(): run(['docker','stop',container])
        self.phase('stop-api-before-owned-maintenance')
        self.compose('stop','api');self.api_stop_started=True
        try: check_resources('after-stop',restore=True)
        except DeploymentError:
            fresh_state();run(['docker','start',info[0]['Id']]);wait_healthy('xiquan-api-1');raise
        self.continue_pre_migration()

    def continue_pre_migration(self):
        before=self.job/'before.json'
        current=query_cloud_state()
        if not before.exists():
            require(current['schema_revision']==OLD and not current['business_state']['maintenance'],'Unclassified pre-claim state')
            require(self.guard('inspect')==self.pre_stop_snapshot,'Pre-stop snapshot changed; do not claim maintenance')
            json_write(before,self.guard('claim'))
        else: require(self.guard('inspect')==json_read(before),'Owned pre-migration baseline changed')
        folder=self.job/'before'
        if folder.exists() and not(folder/'receipt.json').exists(): retain_partial_backup(folder)
        if folder.exists():
            receipt=json_read(folder/'receipt.json')
            require(receipt['restore']['status']=='verified' and digest_file(folder/'database.backup')==receipt['dump_sha256'],'Before backup invalid')
            clone=self.restore(folder/'database.backup')
        else: clone=self.backup('before')
        if (self.job/'clone-proof.json').exists():
            clone.stop()
        else:
            # A failed clone attempt can leave these exact private files; preserve
            # them instead of overwriting credentials or confusing restore proof.
            for name in ('clone-logins.sql','clone.env','clone-before.json','clone-preserved-before-fixtures.json','clone-enable-logins.sql'):
                file=self.job/name
                if file.exists(): file.rename(self.job/(name+'.retained-'+uuid.uuid4().hex))
            self.rehearsal(clone)
        proof=json_read(self.job/'clone-proof.json')
        require(all(proof.get(k) is True for k in ('pg17','isolated','identity_immutable','receipt_immutable','receipt_cleanup','retained_rows')), 'Incomplete 0.5.0 PostgreSQL proof')
        require(self.guard('inspect')==json_read(before),'Production changed during clone proof')
        self.phase('exact-reviewed-identity-and-receipt-migration')
        json_write(self.job/'after.json',self.guard('migrate',baseline='before.json'))
        self.complete_after()

    def complete_after(self):
        require(self.guard('inspect')==json_read(self.job/'after.json'),'Post-migration baseline changed')
        folder=self.job/'after'
        if folder.exists() and not(folder/'receipt.json').exists():
            retained=retain_partial_backup(folder);print('PARTIAL_AFTER_BACKUP_RETAINED='+str(retained),flush=True)
        if folder.exists():
            receipt=json_read(folder/'receipt.json')
            require(receipt['restore']['status']=='verified' and digest_file(folder/'database.backup')==receipt['dump_sha256'],'After backup invalid')
        else: self.backup('after').stop()
        json_write(self.job/'ready.json',dict(image_id=self.context['image_id'],source_commit=self.report['source_commit']))
        self.install();self.finish()

    def resume(self):
        self.phase('classify-exact-050-checkpoint');self.verify_pinned_image()
        require(self.context['stage']==str(self.stage) and self.context['source_commit']==self.report['source_commit'] and
                self.context['tools']=={n:digest_file(Path(__file__).parent/n) for n in TOOLS},'Recovery source/tools differ')
        require(not(self.job/'completed.json').exists(),'Already completed; do not redeploy')
        require(digest_file(CLOUD/'.env')==self.context['env_sha256'],'Private environment changed')
        state=query_cloud_state()
        if state['schema_revision']==OLD:
            require((self.job/'before.json').exists(),'Pre-claim checkpoint needs explicit review; original schema remains')
            self.continue_pre_migration();return
        require(state['schema_revision']==HEAD and (self.job/'after.json').exists(),'Unclassified migration result; never repeat migration or restore blindly')
        if not(self.job/'ready.json').exists(): self.complete_after();return
        ready=json_read(self.job/'ready.json')
        require(ready==dict(image_id=self.context['image_id'],source_commit=self.report['source_commit']),'Ready identity differs')
        if not(self.job/'maintenance-released.json').exists():
            require(self.guard('inspect')==json_read(self.job/'after.json'),'Owned ready baseline changed');self.install()
        self.finish()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['preflight','deploy','resume'])
    for name in ('bundle','sha256','commit','stage','job'): parser.add_argument('--'+name)
    args=parser.parse_args();driver=None
    try:
        require(os.name=='posix' and os.getuid()==0,'Human-run ECS root only');os.umask(0o077)
        import fcntl
        with no_links('/run/lock/xiquan-stock-cutover.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.mode=='preflight': preflight(args.bundle,args.sha256,args.commit)
            else:
                driver=Desktop050(args.stage,args.job if args.mode=='resume' else None)
                require(driver.report['source_commit']==args.commit,'Explicit source commit mismatch')
                getattr(driver,args.mode)()
    except Exception as error:
        message=str(error) if isinstance(error,DeploymentError) else type(error).__name__+': inspect private evidence'
        print('DESKTOP050_STOPPED: '+message,file=sys.stderr)
        if driver and driver.job:
            print('PRIVATE_DESKTOP_JOB='+str(driver.job),file=sys.stderr)
            print('FAILED_PHASE='+getattr(driver,'last_phase','precheck'),file=sys.stderr)
        return 1
    finally:
        if driver:
            for restore in driver.restores:
                try: restore.stop()
                except Exception: pass
    return 0


if __name__=='__main__': raise SystemExit(main())
