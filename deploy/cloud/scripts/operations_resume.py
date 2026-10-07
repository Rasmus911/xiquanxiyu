"""Resume the verified offline image checkpoint; never rebuild or clear data."""
import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

if os.name == 'posix':
    import fcntl

from operations_backup_verify import DeploymentError, IsolatedRestore, inspect_database, run, verify_full_restore
from operations_deploy import json_read
from operations_offline_build import (checked_job, expected_payload, latest_phase, probe_image,
    require_dependencies, requirements_digest)
from operations_preflight import no_links


def require_verified_image(receipt, context, image, proof, expected_requirements, payload):
    config = image.get('Config', {})
    if (receipt.get('status') != 'offline_image_verified'
            or receipt.get('source_commit') != context['source_commit']
            or receipt.get('image_id') != image.get('Id')
            or receipt.get('base_image_id') != context['old_api_image']
            or receipt.get('production_unchanged') is not True
            or receipt.get('api_started') is not False
            or receipt.get('migration_performed') is not False
            or receipt.get('requirements_sha256') != expected_requirements
            or config.get('Labels', {}).get('org.opencontainers.image.revision') != context['source_commit']
            or config.get('WorkingDir') != '/app' or config.get('User') != 'xiquan'
            or config.get('Entrypoint') != ['/app/docker-entrypoint.sh']
            or config.get('Cmd') != ['python', 'run.py']):
        raise DeploymentError('Verified image receipt, source or startup identity changed')
    require_dependencies(proof, expected_requirements)
    if (proof.get('payload') != payload or any(receipt.get(key) != proof.get(key)
            for key in ('pg_dump', 'pg_restore'))):
        raise DeploymentError('Actual image payload or PG17 tools differ from the verified checkpoint')


def require_pristine_checkpoint(phase, job):
    artifacts = ('isolated-role-login.sql', 'rehearsal.env', 'rehearsal', 'rehearsal-verify.env',
        'rehearsal-verified.json', 'owner-check', 'post-migration', 'restore.env',
        'preview.json', 'prepared.json', 'business-verified.json', 'completed.json')
    if phase != 'build-new-api-image-offline-verified' or any(
            (job / name).exists() or (job / name).is_symlink() for name in artifacts):
        raise DeploymentError('Not a pristine verified image checkpoint; retain evidence, do not repeat migration')


def parse_environment(content):
    values = {}
    for line in content.splitlines():
        key, separator, value = line.partition('=')
        if (not separator or not re.fullmatch('[A-Z][A-Z0-9_]*', key) or key in values
                or any(character in value for character in '\r\n\0')):
            raise DeploymentError('Private environment format is invalid; values were not printed')
        values[key] = value
    return values


def require_isolated_clone(info, context, verified, variables):
    name = verified['restore_container']
    if (not re.fullmatch('xiquan-operations-restore-[0-9a-f]{32}', name)
            or verified['restore_volume'] != name + '-data'
            or set(variables) != {'POSTGRES_USER', 'POSTGRES_DB', 'POSTGRES_PASSWORD'}
            or variables.get('POSTGRES_USER') != 'operations_restore'
            or variables.get('POSTGRES_DB') != 'operations_restore'
            or not re.fullmatch('[A-Za-z0-9_-]{16,128}', variables.get('POSTGRES_PASSWORD', ''))):
        raise DeploymentError('Original isolated restore identity or private environment is invalid')
    actual_env = dict(value.split('=', 1) for value in info['Config'].get('Env', []) if '=' in value)
    data_mounts = [mount for mount in info.get('Mounts', [])
        if mount.get('Destination') == '/var/lib/postgresql/data']
    if (info.get('Name') != '/' + name or info.get('Image') != context['postgres_image']
            or not info['State'].get('Running') or info['State'].get('Health', {}).get('Status') != 'healthy'
            or info['Config'].get('Labels', {}).get('xiquan.operations.restore') != name
            or set(info['NetworkSettings']['Networks']) != {context['network']}
            or info['HostConfig'].get('PortBindings')
            or len(data_mounts) != 1 or data_mounts[0].get('Type') != 'volume'
            or data_mounts[0].get('Name') != verified['restore_volume']
            or any(actual_env.get(key) != value for key, value in variables.items())):
        raise DeploymentError('Existing restore container is not the original private healthy clone')


def resume_remaining(operations):
    operations.rehearsal()
    operations.migrate()
    operations.snapshot_restore()
    preview = operations.preview()
    if not preview.get('can_apply'):
        raise DeploymentError('Business preview has conflicts; no application or API restart performed')
    operations.save_preview(preview)


def private_file(path):
    path = no_links(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
        raise DeploymentError('Private recovery evidence has unsafe ownership or permissions')
    return path


def restore_checkpoint(deployment, image_receipt):
    job, context = deployment.job, deployment.context
    require_pristine_checkpoint(latest_phase(job), job)
    receipt_path = no_links(image_receipt)
    if not re.fullmatch(re.escape(str(job)) + '/offline-image-[0-9a-f]{32}/verified-image.json', str(receipt_path)):
        raise DeploymentError('Image receipt must belong to this recovery job')
    receipt = json_read(private_file(receipt_path))
    image = json.loads(run(['docker', 'image', 'inspect', context['new_image']]))[0]
    proof = probe_image(context['new_image'])
    server = deployment.source / 'server'
    require_verified_image(receipt, context, image, proof,
        requirements_digest(no_links(server / 'requirements.txt').read_bytes()), expected_payload(server))
    deployment.resolve_environment()
    saved = parse_environment(private_file(job / 'maintenance.env').read_text(encoding='utf-8'))
    if saved != deployment.env:
        raise DeploymentError('Maintenance configuration changed since the verified backup; no rotation allowed')
    api = json.loads(run(['docker', 'inspect', 'xiquan-api-1']))[0]
    normal = dict(value.split('=', 1) for value in api['Config']['Env'] if '=' in value)
    if any(normal.get(key, '') != deployment.normal_env.get(key, '') for key in
            ('SECRET_KEY', 'JWT_SECRET_KEY', 'AUDIT_HMAC_KEY', 'DATABASE_URL')):
        raise DeploymentError('Existing runtime or signing configuration changed')
    network = json.loads(run(['docker', 'network', 'inspect', context['network']]))[0]
    postgres = json.loads(run(['docker', 'inspect', 'xiquan-postgres-1']))[0]
    if (network.get('Internal') is not True or postgres['Image'] != context['postgres_image']
            or not postgres['State'].get('Running')
            or postgres['State'].get('Health', {}).get('Status') != 'healthy'
            or context['network'] not in postgres['NetworkSettings']['Networks']):
        raise DeploymentError('Original private PG17 production container or network identity changed')
    verified = json_read(private_file(job / 'pre-migration-verified.json'))
    name = verified['restore_container']
    if not re.fullmatch('xiquan-operations-restore-[0-9a-f]{32}', name):
        raise DeploymentError('Unexpected original restore name')
    variables = parse_environment(private_file(job / (name + '.env')).read_text(encoding='utf-8'))
    info = json.loads(run(['docker', 'inspect', name]))[0]
    require_isolated_clone(info, context, verified, variables)
    volume = json.loads(run(['docker', 'volume', 'inspect', verified['restore_volume']]))[0]
    if (volume.get('Name') != verified['restore_volume']
            or (volume.get('Labels') or {}).get('xiquan.operations.restore') != name):
        raise DeploymentError('Original isolated volume identity changed')
    actual = inspect_database(name)
    if actual != verified['restored']:
        raise DeploymentError('Original restored rows changed; no rehearsal or migration authorized')
    verify_full_restore(verified['source'], actual)
    restore = IsolatedRestore(job, context['postgres_image'], context['network'])
    restore.name, restore.volume = name, verified['restore_volume']
    restore.password, restore.started = variables['POSTGRES_PASSWORD'], True
    deployment.pre_restore = restore
    print('VERIFIED_OFFLINE_CHECKPOINT_RESUMED_NO_REBUILD', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--image-receipt', required=True)
    args = parser.parse_args()
    try:
        if os.name != 'posix' or os.getuid() != 0:
            raise DeploymentError('Run as root on the existing ECS, not on Windows')
        with no_links('/run/lock/xiquan-operations-cutover.lock').open('r+') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DeploymentError('Another cutover is still running; no process was signalled') from None
            deployment = checked_job(args.stage, args.job)
            restore_checkpoint(deployment, args.image_receipt)
            # All original data/evidence guards remain in the unchanged driver.
            resume_remaining(deployment)
    except Exception as error:
        message = str(error) if isinstance(error, DeploymentError) else 'Resume stopped; raw errors and credentials were not printed'
        print('DEPLOY_RESUME_STOPPED: ' + message, file=sys.stderr)
        print('Private evidence retained. Do not repeat Prepare, start an old API or restore a dump blindly.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
