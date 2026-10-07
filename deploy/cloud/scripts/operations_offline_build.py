"""Recover ONLY the stalled pre-migration image build, without installing packages.

Reuses a pinned local image only after checking the requirements, installed
versions and PG17 tools. It never starts an API or migrates a production DB.
"""
import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

if os.name == 'posix':
    import fcntl

from operations_backup_verify import DeploymentError, inspect_database, run
from operations_preflight import digest_file, no_links, query_cloud_state
from operations_deploy import Deployment, json_read, json_write, require_idle

BUILD_PHASES = {'build-new-api-image', 'build-new-api-image-offline-recovery',
                'build-new-api-image-offline-verified'}

IMAGE_PROBE = r'''
import hashlib, importlib.metadata as md, json, subprocess, sys
from pathlib import Path
from pip._vendor.packaging.requirements import Requirement
content=Path('/app/requirements.txt').read_text(encoding='utf-8-sig')
normalized='\n'.join(content.splitlines())+'\n'
compatible=True
for line in content.splitlines():
    if not line.strip() or line.lstrip().startswith('#'): continue
    req=Requirement(line)
    if req.marker and not req.marker.evaluate(): continue
    try: version=md.version(req.name)
    except md.PackageNotFoundError: compatible=False; continue
    if not req.specifier.contains(version): compatible=False
    if req.name=='psycopg' and 'binary' in req.extras:
        try: compatible=compatible and md.version('psycopg-binary')==version
        except md.PackageNotFoundError: compatible=False
result={'requirements_sha256':hashlib.sha256(normalized.encode()).hexdigest(),
        'compatible':compatible,'python':list(sys.version_info[:2])}
for name in ('pg_dump','pg_restore'):
    result[name]=subprocess.check_output(['/usr/lib/postgresql/17/bin/'+name,'--version'],text=True).strip()
files={}
for root in ('app','migrations'):
    for path in Path('/app',root).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and not path.name.endswith(('.pyc','.pyo')):
            files[str(path.relative_to('/app'))]=hashlib.sha256(path.read_bytes()).hexdigest()
for name in ('run.py','docker-entrypoint.sh'):
    data=Path('/app',name).read_bytes()
    if name=='docker-entrypoint.sh': data=data.replace(b'\r\n',b'\n')
    files[name]=hashlib.sha256(data).hexdigest()
result['payload']=files
print(json.dumps(result))
'''


def require_build_only(phase, state):
    if phase not in BUILD_PHASES or state.get('schema_revision') != '20261003_preserve_administrators':
        raise DeploymentError('Not an unchanged pre-migration build; do not recover or restart blindly')
    require_idle(state)


def exact_build(args, image, source):
    return bool(args and Path(args[0]).name == 'docker'
                and args[1:] == ['build', '--tag', image, source])


def require_dependencies(proof, expected):
    if (proof.get('requirements_sha256') != expected or proof.get('python') != [3, 12]
            or proof.get('compatible') is not True or any(
                not re.match(r'^'+name+r' \(PostgreSQL\) 17\.', str(proof.get(name, '')))
                for name in ('pg_dump', 'pg_restore'))):
        raise DeploymentError('Local base dependencies/PG17 tools differ; no cancellation or reuse authorized')


def requirements_digest(content):
    normalized = '\n'.join(content.decode('utf-8-sig').splitlines()) + '\n'
    return hashlib.sha256(normalized.encode()).hexdigest()


def stream_build(argv, log):
    try:
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except OSError:
        raise DeploymentError('Build evidence already exists or cannot be created') from None
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            output.write(line); output.flush()
            print(line.rstrip(), flush=True)
        if process.wait() != 0:
            raise DeploymentError('Offline image build failed; private build output retained')


def latest_phase(job):
    phases = [no_links(path) for path in job.glob('phase-*.json')]
    if not phases: raise DeploymentError('No recorded deployment phase')
    return json_read(max(phases, key=lambda path: path.stat().st_mtime_ns))['phase']


def checked_job(stage, job):
    job = no_links(job)
    if not re.fullmatch('/opt/xiquan-backups/operations-cutover-[0-9a-f]{32}', str(job)):
        raise DeploymentError('Unexpected recovery directory')
    info = job.stat()
    if info.st_uid != 0 or info.st_mode & 0o077:
        raise DeploymentError('Recovery directory must be root-owned and private')
    context = json_read(job / 'context.json')
    if context.get('stage') != str(stage): raise DeploymentError('Recovery job belongs to another source stage')
    for name in ('operations_deploy.py','operations_backup_verify.py','operations_preflight.py'):
        if digest_file(Path(__file__).parent / name) != context['deployment_tools'][name]:
            raise DeploymentError('Original reviewed deployment tools changed')
    deployment = Deployment(stage, job=job)
    if context['source_commit'] != deployment.report['source_commit']:
        raise DeploymentError('Source commit differs from this stopped deployment')
    deployment.protected_check()
    require_build_only(latest_phase(job), query_cloud_state())
    api = json.loads(run(['docker','inspect','xiquan-api-1']))[0]
    if api['State']['Running'] or api['Image'] != context['old_api_image']:
        raise DeploymentError('Original API is running or its identity changed; no takeover')
    verified = json_read(job / 'pre-migration-verified.json')
    if (digest_file(job / 'pre-migration.backup') != verified['dump_sha256']
            or inspect_database('xiquan-postgres-1') != verified['source']):
        raise DeploymentError('Verified pre-migration backup or production data changed')
    return deployment


def process_args(pid):
    try:
        return Path('/proc', str(pid), 'cmdline').read_bytes().decode().strip('\0').split('\0')
    except (OSError, UnicodeError):
        return []


def take_build_lock(deployment, handle):
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    except BlockingIOError:
        pass
    expected = ['--mode', 'prepare', '--stage', str(deployment.stage)]
    candidates = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit(): continue
        args = process_args(path.name)
        if (len(args) != 6 or Path(args[0]).name not in {'python','python3'}
                or not re.fullmatch('/tmp/xiquan-operations-cutover-tools-[0-9a-f]{32}/operations_deploy.py', args[1])
                or args[2:] != expected): continue
        for child in Path('/proc').iterdir():
            if not child.name.isdigit(): continue
            try:
                status = (child / 'status').read_text()
            except OSError: continue
            if not re.search(r'^PPid:\s*'+path.name+r'\s*$', status, re.MULTILINE): continue
            child_args = process_args(child.name)
            if exact_build(child_args, deployment.context['new_image'], str(deployment.source / 'server')):
                candidates.append((int(child.name), child_args))
    if len(candidates) != 1:
        raise DeploymentError('Lock held but no unique matching Docker build; nothing was signalled')
    require_build_only(latest_phase(deployment.job), query_cloud_state())
    pid, args = candidates[0]
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise DeploymentError('Safe process-handle signalling unavailable; nothing was signalled')
    descriptor = os.pidfd_open(pid)
    try:
        if process_args(pid) != args: raise DeploymentError('Build process identity changed')
        signal.pidfd_send_signal(descriptor, signal.SIGINT)
    finally:
        os.close(descriptor)
    print('ONLY_MATCHED_STALLED_DOCKER_BUILD_INTERRUPTED', flush=True)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            time.sleep(1)
    raise DeploymentError('Original deployment did not release its lock; do not start a second build')


def probe_image(image, *, memory_mib=None):
    limits = []
    if memory_mib is not None:
        if type(memory_mib) is not int or not 128 <= memory_mib <= 512:
            raise DeploymentError('Invalid bounded image probe memory limit')
        limits = ['--memory', f'{memory_mib}m', '--memory-swap', f'{memory_mib}m', '--cpus', '1', '--pids-limit', '128']
    return json.loads(run(['docker','run','--rm',*limits,'--network','none','--entrypoint','python',image,'-B','-c',IMAGE_PROBE], timeout=90))


def expected_payload(server):
    files = {}
    for root in ('app','migrations'):
        for path in (server / root).rglob('*'):
            if path.is_file(): files[str(path.relative_to(server)).replace('\\','/')]=digest_file(path)
    for name in ('run.py','docker-entrypoint.sh'):
        content = no_links(server / name).read_bytes()
        if name == 'docker-entrypoint.sh': content=content.replace(b'\r\n',b'\n')
        files[name]=hashlib.sha256(content).hexdigest()
    return files


def recover(stage, job):
    deployment = checked_job(stage, job)
    expected = requirements_digest(no_links(deployment.source / 'server/requirements.txt').read_bytes())
    proof = probe_image(deployment.context['old_api_image'])
    require_dependencies(proof, expected)
    base = 'xiquan-api:rollback-' + deployment.job.name[-32:]
    base_info=json.loads(run(['docker','image','inspect',base]))[0]
    if base_info['Id'] != deployment.context['old_api_image']:
        raise DeploymentError('Preserved local rollback image identity changed')
    image_config=base_info['Config']
    if (image_config.get('WorkingDir') != '/app' or image_config.get('User') != 'xiquan'
            or image_config.get('Entrypoint') != ['/app/docker-entrypoint.sh']
            or image_config.get('Cmd') != ['python','run.py']):
        raise DeploymentError('Local image startup contract differs; no reuse')
    print('PINNED_LOCAL_IMAGE_DEPENDENCIES_AND_PG17_VERIFIED', flush=True)
    lock = no_links('/run/lock/xiquan-operations-cutover.lock')
    with lock.open('r+') as handle:
        take_build_lock(deployment, handle)
        deployment = checked_job(stage, job)
        nonce = uuid.uuid4().hex
        attempt = deployment.job / ('offline-image-' + nonce)
        attempt.mkdir(mode=0o700)
        if json.loads(run(['docker','image','inspect',base]))[0]['Id'] != deployment.context['old_api_image']:
            raise DeploymentError('Preserved local rollback image identity changed')
        dockerfile=attempt / 'Dockerfile'
        dockerfile.write_text('FROM '+base+'\nUSER root\n'
            '# Only removes code inside the new image layer; no host paths or volumes.\n'
            'RUN test -d /app/app && test -d /app/migrations && rm -rf /app/app /app/migrations\n'
            'COPY --chown=xiquan:xiquan app /app/app\n'
            'COPY --chown=xiquan:xiquan migrations /app/migrations\n'
            'COPY --chown=xiquan:xiquan run.py docker-entrypoint.sh /app/\n'
            'RUN sed -i \'s/\\r$//\' /app/docker-entrypoint.sh && chmod 0755 /app/docker-entrypoint.sh\n'
            'USER xiquan\nLABEL org.opencontainers.image.revision="'+deployment.context['source_commit']+'"\n', encoding='utf-8')
        dockerfile.chmod(0o600)
        temporary='xiquan-api:offline-verified-'+nonce
        deployment.phase('build-new-api-image-offline-recovery')
        stream_build(['docker','build','--progress=plain','--pull=false','--network=none',
            '--file',str(dockerfile),'--tag',temporary,str(deployment.source / 'server')], attempt / 'build.log')
        result=probe_image(temporary)
        require_dependencies(result,expected)
        if result['payload'] != expected_payload(deployment.source / 'server'):
            raise DeploymentError('New image code differs from the verified staged payload')
        image=json.loads(run(['docker','image','inspect',temporary]))[0]
        if image['Config'].get('Labels',{}).get('org.opencontainers.image.revision') != deployment.context['source_commit']:
            raise DeploymentError('New image source identity was not retained')
        deployment=checked_job(stage,job)
        run(['docker','tag',temporary,deployment.context['new_image']])
        json_write(attempt / 'verified-image.json', dict(status='offline_image_verified',
            source_commit=deployment.context['source_commit'],image_id=image['Id'],
            base_image_id=deployment.context['old_api_image'],requirements_sha256=expected,
            pg_dump=result['pg_dump'],pg_restore=result['pg_restore'],production_unchanged=True,
            api_started=False,migration_performed=False))
        deployment.phase('build-new-api-image-offline-verified')
        print('OFFLINE_API_IMAGE_VERIFIED_OK', flush=True)
        print('PRIVATE_IMAGE_RECEIPT='+str(attempt / 'verified-image.json'),flush=True)
        print('API remains stopped. No migration, cutover, publication or cleanup performed.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',required=True)
    parser.add_argument('--job',required=True)
    args=parser.parse_args()
    try:
        if os.name != 'posix' or os.getuid() != 0:
            raise DeploymentError('Run as root on the existing ECS, not on Windows')
        recover(args.stage,args.job)
    except Exception as error:
        message=str(error) if isinstance(error,DeploymentError) else 'Offline recovery stopped; raw errors and credentials were not printed'
        print('OFFLINE_BUILD_STOPPED: '+message,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
