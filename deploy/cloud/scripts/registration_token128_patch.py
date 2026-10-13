"""Narrow human-run API hotfix: no schema, account, database or desktop changes."""
import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

BASE_SHA256 = '90622cb03f6b5782a7b25dab0f618230cba6a53bec399d8c9944b1591b7a6845'
PATCH_SHA256 = '31889af111c17074a4cbb49ed1f610fa6338efea46e4698a87cdf91b71d4724b'
CLOUD = Path('/opt/xiquan/xiquan/deploy/cloud')
SOURCE = Path('/opt/xiquan/xiquan/server/app/api/mobile.py')


def normalized_hash(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def verify_patch(previous, incoming, expected):
    if not re.fullmatch('[0-9a-f]{64}', expected) or hashlib.sha256(incoming).hexdigest() != expected:
        raise ValueError('Uploaded patch SHA256 mismatch; nothing changed')
    if normalized_hash(incoming) != PATCH_SHA256:
        raise ValueError('Patch differs from reviewed mobile capability hotfix')
    if normalized_hash(previous) not in (BASE_SHA256, PATCH_SHA256):
        raise ValueError('Existing API source differs from the reviewed 0.4.9 baseline; nothing changed')
    ast.parse(incoming.decode('utf-8'))


def safe_path(path):
    value = Path(path)
    if not value.is_absolute() or any(p.is_symlink() for p in (value, *value.parents)):
        raise ValueError('Unexpected linked or relative deployment path')
    return value


def escape_compose(value):
    # A resolved config must not interpolate dollar signs in secret values again.
    if isinstance(value, str): return value.replace('$', '$$')
    if isinstance(value, dict): return {k: escape_compose(v) for k, v in value.items()}
    if isinstance(value, list): return [escape_compose(v) for v in value]
    return value


def verify_runtime(config, image, runtime):
    service = config['services']['api']
    actual = runtime['Config']
    environment = dict(value.split('=', 1) for value in image.get('Env', []))
    environment.update({key: str(value) for key, value in service.get('environment', {}).items()})
    if environment != dict(value.split('=', 1) for value in actual.get('Env', [])):
        raise ValueError('Resolved API environment differs from running API; no restart performed')
    for compose_key, docker_key in [('command', 'Cmd'), ('entrypoint', 'Entrypoint'),
                                    ('user', 'User'), ('working_dir', 'WorkingDir')]:
        expected = service.get(compose_key)
        if expected is None: expected = image.get(docker_key)
        if expected != actual.get(docker_key):
            raise ValueError('Resolved API process settings differ; no restart performed')
    expected_mounts = []
    for mount in service.get('volumes', []):
        if mount['type'] == 'bind': source = mount['source']
        elif mount['type'] == 'volume': source = config['volumes'][mount['source']]['name']
        else: raise ValueError('Unreviewed API mount type')
        expected_mounts.append((mount['type'], source, mount['target'], not mount.get('read_only', False)))
    actual_mounts = [(mount['Type'], mount.get('Name') if mount['Type'] == 'volume' else mount['Source'],
                       mount['Destination'], mount['RW']) for mount in runtime.get('Mounts', [])]
    if sorted(expected_mounts) != sorted(actual_mounts):
        raise ValueError('Resolved API mounts differ; no restart performed')
    expected_networks = {config['networks'][key]['name'] for key in service.get('networks', {})}
    if expected_networks != set(runtime['NetworkSettings']['Networks']):
        raise ValueError('Resolved API networks differ; no restart performed')
    host = runtime['HostConfig']
    if service.get('ports') or host.get('PortBindings'):
        raise ValueError('Unexpected API public port bindings; no restart performed')
    if (service.get('restart', '') != host.get('RestartPolicy', {}).get('Name', '') or
        int(service.get('mem_limit', 0)) != host.get('Memory', 0) or
        int(float(service.get('cpus', 0)) * 1_000_000_000) != host.get('NanoCpus', 0) or
        bool(service.get('read_only', False)) != host.get('ReadonlyRootfs', False)):
        raise ValueError('Resolved API limits or restart settings differ; no restart performed')


def verify_origin_health(run):
    # Do not negotiate HTTP/2: curl exit 16 is a transport failure, not an
    # unhealthy API. Keep certificate/SNI validation and HTTP error checking.
    return run(['curl', '--http1.1', '--fail', '--silent', '--show-error', '--max-time', '20',
                '--resolve', 'api.pqxqxy.xyz:443:127.0.0.1', '--noproxy', 'api.pqxqxy.xyz',
                'https://api.pqxqxy.xyz/api/health'])


def deploy(incoming_path, expected):
    incoming_path = safe_path(incoming_path)
    source = safe_path(SOURCE)
    incoming = incoming_path.read_bytes()
    verify_patch(source.read_bytes(), incoming, expected)
    job = safe_path('/opt/xiquan-backups') / ('registration-token128-' + uuid.uuid4().hex)
    job.mkdir(mode=0o700)
    print('PRIVATE_TOKEN_PATCH_JOB=' + str(job), flush=True)

    def run(args, timeout=120):
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            evidence = job / ('command-failure-' + uuid.uuid4().hex + '.json')
            evidence.write_text(json.dumps({'exit': result.returncode,
                'stdout': result.stdout.decode('utf-8', errors='replace'),
                'stderr': result.stderr.decode('utf-8', errors='replace')}), encoding='utf-8')
            evidence.chmod(0o600)
            raise ValueError('Command failed; private evidence=' + str(evidence))
        return result.stdout

    api = json.loads(run(['docker', 'inspect', 'xiquan-api-1']))[0]
    if api['State']['Status'] != 'running' or api['State'].get('Health', {}).get('Status') != 'healthy':
        raise ValueError('Existing API must be healthy before this narrow patch; no restart performed')
    maintenance = run(['docker', 'exec', 'xiquan-api-1', 'python', '-c',
        "import os,json;from sqlalchemy import create_engine,text;"
        "e=create_engine(os.environ['DATABASE_URL']);"
        "c=e.connect();c.execute(text('SET TRANSACTION READ ONLY'));"
        "v=c.execute(text('SELECT maintenance FROM business_state WHERE id=1')).scalar();"
        "print(json.dumps(v));c.rollback();c.close()"])
    if json.loads(maintenance) is not False:
        raise ValueError('Existing maintenance state blocks the patch; no restart performed')
    labels = api['Config']['Labels']
    if labels.get('com.docker.compose.project') != 'xiquan' or labels.get('com.docker.compose.service') != 'api':
        raise ValueError('Unexpected API Compose identity')
    files = labels.get('com.docker.compose.project.config_files', '').split(',')
    for file in files:
        path = safe_path(file)
        if not path.is_file() or not (str(path).startswith('/opt/xiquan/') or str(path).startswith('/opt/xiquan-backups/')):
            raise ValueError('Original Compose stack missing or unexpected; no restart performed')
    command = ['docker', 'compose', '--project-directory', str(CLOUD), '--env-file', str(CLOUD / '.env'), '-p', 'xiquan']
    for file in files: command += ['-f', file]
    resolved = json.loads(run(command + ['config', '--format', 'json']))
    image_config = json.loads(run(['docker', 'image', 'inspect', api['Image']]))[0]['Config']
    verify_runtime(resolved, image_config, api)
    runtime_hash = run(['docker', 'exec', 'xiquan-api-1', 'python', '-c',
        "import hashlib;from pathlib import Path;print(hashlib.sha256(Path('/app/app/api/mobile.py').read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest())"]).decode().strip()
    if runtime_hash not in (BASE_SHA256, PATCH_SHA256):
        raise ValueError('Running API differs from the reviewed baseline; no restart performed')
    shutil.copy2(source, job / 'mobile.py.before')
    (job / 'mobile.py').write_bytes(incoming)
    suffix = job.name.rsplit('-', 1)[1]
    base = 'xiquan-api:registration-token128-base-' + suffix
    candidate = 'xiquan-api:registration-token128-' + suffix
    run(['docker', 'tag', api['Image'], base])
    (job / 'Dockerfile').write_text('FROM ' + base + '\nCOPY --chown=xiquan:xiquan mobile.py /app/app/api/mobile.py\n', encoding='utf-8')
    print('TOKEN_PATCH_PHASE=offline-local-image-build', flush=True)
    run(['docker', 'build', '--pull=false', '--network=none', '-t', candidate, str(job)], timeout=180)
    new_image = json.loads(run(['docker', 'image', 'inspect', candidate]))[0]['Id']
    run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python', candidate, '-c',
        "import ast;from pathlib import Path;ast.parse(Path('/app/app/api/mobile.py').read_text());print('COMPILE_OK')"])
    def frozen_stack(name, image_id):
        config = copy.deepcopy(resolved)
        config['services']['api']['image'] = image_id
        path = job / name
        path.write_text(json.dumps(escape_compose(config), indent=2), encoding='utf-8')
        path.chmod(0o600)
        return path
    candidate_stack = frozen_stack('candidate-stack.json', new_image)
    original_stack = frozen_stack('original-stack.json', api['Image'])
    checkpoint = {'old_image': api['Image'], 'new_image': new_image,
                  'source_sha256': expected, 'compose_files': files,
                  'candidate_stack': str(candidate_stack), 'original_stack': str(original_stack)}
    (job / 'ready.json').write_text(json.dumps(checkpoint, indent=2), encoding='utf-8')

    def replace_source(data):
        stat = source.stat()
        staged = source.with_name('mobile.py.token128-' + uuid.uuid4().hex)
        staged.write_bytes(data); shutil.copystat(source, staged)
        os.chown(staged, stat.st_uid, stat.st_gid); os.replace(staged, source)

    def start_and_verify(stack, image_id):
        run(['docker', 'compose', '--project-directory', str(CLOUD), '-p', 'xiquan', '-f', str(stack),
             'up', '-d', '--no-build', '--no-deps', '--pull', 'never', 'api'])
        for _ in range(45):
            current = json.loads(run(['docker', 'inspect', 'xiquan-api-1']))[0]
            if current['Image'] != image_id: raise ValueError('API image differs from verified checkpoint')
            if current['State'].get('Health', {}).get('Status') == 'healthy': break
            if current['State']['Status'] == 'exited': raise ValueError('API exited; preserve checkpoint and logs')
            time.sleep(2)
        else: raise ValueError('API did not become healthy; preserve checkpoint and logs')
        verify_runtime(resolved, image_config, current)
        run(['docker', 'exec', 'xiquan-nginx-1', 'nginx', '-t'])
        run(['docker', 'exec', 'xiquan-nginx-1', 'nginx', '-s', 'reload'])
        verify_origin_health(run)

    # Only the code/image are changed. The private resolved stack freezes the
    # validated running settings, including worker/secrets, before any cutover.
    replace_source(incoming)
    try:
        print('TOKEN_PATCH_PHASE=recreate-api-preserving-original-settings', flush=True)
        start_and_verify(candidate_stack, new_image)
    except Exception:
        print('TOKEN_PATCH_PHASE=restore-original-api-code-and-image-only', flush=True)
        if normalized_hash(source.read_bytes()) != PATCH_SHA256:
            raise ValueError('Source drift after cutover; preserve private checkpoint')
        replace_source((job / 'mobile.py.before').read_bytes())
        start_and_verify(original_stack, api['Image'])
        (job / 'original-api-restored.json').write_text(json.dumps(checkpoint), encoding='utf-8')
        raise ValueError('Hotfix verification failed; original API restored and health checked; no database rollback')
    (job / 'completed.json').write_text(json.dumps(checkpoint, indent=2), encoding='utf-8')
    print('REGISTRATION_TOKEN128_API_PATCH_OK; no migration, account edits, financial changes or desktop publication')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if os.name != 'posix' or os.getuid() != 0: raise SystemExit('Human-run ECS root only')
    import fcntl
    os.umask(0o077)
    try:
        with safe_path('/run/lock/xiquan-stock-cutover.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            deploy(args.source, args.sha256)
    except Exception as error:
        print('TOKEN_PATCH_STOPPED: ' + str(error), flush=True)
        raise SystemExit(1)
