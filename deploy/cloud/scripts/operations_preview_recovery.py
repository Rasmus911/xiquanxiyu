"""Recover the failed private preview after verified migration; no schema changes."""
import argparse
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path

if os.name == 'posix':
    import fcntl

from operations_backup_verify import DeploymentError
from operations_deploy import Deployment, EXPECTED_SCHEMA, MOUNT, apply, json_read, json_write, require_idle
from operations_offline_build import expected_payload, latest_phase, probe_image, requirements_digest
from operations_preflight import digest_file, no_links, query_cloud_state
from operations_resume import parse_environment, private_file, require_verified_image


class PrivateOutputDeployment(Deployment):
    def output_directory(self):
        directory = self.job / ('preview-recovery-evidence-' + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        return directory

    def maintenance(self, arguments, *, environment=None, python=False):
        argv = ['docker', 'run', '--rm', '--user', '0:0', '--network', self.context['network'],
            '--env-file', str(environment or self.job / 'maintenance.env'),
            '--mount', 'type=bind,src=' + str(self.job) + ',dst=' + MOUNT,
            '--entrypoint', 'python' if python else 'flask', self.context['new_image']]
        argv += arguments if python else ['--app', 'run.py'] + arguments
        # Raw stderr can contain private DSNs. Retain it privately, never echo it.
        directory = self.output_directory()
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
        except Exception as error:
            json_write(directory / 'command-failure.json', {'type': type(error).__name__})
            raise DeploymentError('Maintenance process failed; PRIVATE_DIAGNOSTIC_DIRECTORY=' + str(directory)) from None
        if result.returncode:
            json_write(directory / 'command-failure.json', {'returncode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr})
            raise DeploymentError('Maintenance command failed; PRIVATE_DIAGNOSTIC_DIRECTORY=' + str(directory))
        return result.stdout.strip()

    def promote_output(self, source, name):
        if not re.fullmatch('[a-z][a-z0-9-]*\\.json', name):
            raise DeploymentError('Unexpected private output name')
        data = json_read(private_file(source))
        json_write(self.job / name, data)
        return data

    def preview(self):
        self.phase('private-business-preview-nested')
        directory = self.output_directory()
        relative = directory.name + '/preview.json'
        result = json.loads(self.maintenance(['operations-upgrade', 'preview', '--output', MOUNT + '/' + relative]))
        self.promote_output(directory / 'preview.json', 'preview.json')
        return result

    def inspect_current(self, name):
        directory = self.output_directory()
        relative = directory.name + '/checks.json'
        code = 'from app import create_app; from app.operations_backup import collect_snapshot_checks,_postgres_snapshot_begin,write_private_json; from app.operations_upgrade import maintenance_connection; from pathlib import Path; app=create_app();\n'
        code += "with app.app_context(), maintenance_connection() as c:\n _postgres_snapshot_begin(c); checks=collect_snapshot_checks(c); write_private_json(Path('" + MOUNT + '/' + relative + "'),checks); c.rollback()"
        self.maintenance(['-c', code], python=True)
        self.promote_output(directory / 'checks.json', name)


def require_post_migration_checkpoint(phase, state, rehearsal, receipt, candidate, dump_sha):
    if phase not in {'private-business-preview', 'private-business-preview-nested'}:
        raise DeploymentError('Not the failed private preview checkpoint; do not repeat migration')
    require_idle(state)
    if (state['schema_revision'] != EXPECTED_SCHEMA or rehearsal.get('pg_major') != 17
            or any(rehearsal.get(key) is not True for key in ('actual_migration', 'actual_restore',
                'actual_apply', 'role_and_lock_exercise', 'production_unchanged'))
            or rehearsal.get('active_wristbands') != 100 or rehearsal.get('formal_items') != 42
            or receipt.get('restore', {}).get('status') != 'verified'
            or receipt['restore'].get('pg_major') != 17
            or not receipt['restore'].get('source_server_id') or not receipt['restore'].get('restored_server_id')
            or receipt['restore']['source_server_id'] == receipt['restore']['restored_server_id']
            or receipt.get('dump_sha256') != dump_sha or candidate.get('dump_sha256') != dump_sha
            or receipt.get('dump_size', 0) <= 0 or receipt['dump_size'] != candidate.get('dump_size')
            or candidate['checks']['identity']['alembic_revision'] != EXPECTED_SCHEMA):
        raise DeploymentError('Verified rehearsal, schema or actual PG17 restore evidence differs; no takeover')


def check_existing_job(stage, job, image_receipt, *, preparing):
    job = no_links(job)
    if not re.fullmatch('/opt/xiquan-backups/operations-cutover-[0-9a-f]{32}', str(job)):
        raise DeploymentError('Only the existing private recovery directory is accepted')
    info = job.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
        raise DeploymentError('Recovery directory must remain root-owned and private')
    operations = PrivateOutputDeployment(stage, job=job)
    context = operations.context
    if context['stage'] != str(operations.stage) or context['source_commit'] != operations.report['source_commit']:
        raise DeploymentError('Recovery source identity changed')
    for name in ('operations_deploy.py', 'operations_backup_verify.py', 'operations_preflight.py'):
        if digest_file(Path(__file__).parent / name) != context['deployment_tools'][name]:
            raise DeploymentError('Original reviewed deployment tools changed')
    operations.protected_check()
    if preparing and any((job / name).exists() for name in
            ('preview.json', 'prepared.json', 'business-verified.json', 'old-files', 'completed.json')):
        raise DeploymentError('Business preparation or application already exists; nothing is overwritten')
    if not re.fullmatch(re.escape(str(job)) + '/offline-image-[0-9a-f]{32}/verified-image.json', str(image_receipt)):
        raise DeploymentError('Image receipt belongs to another recovery job')
    receipt = json_read(private_file(image_receipt))
    # Import the unchanged safe Docker boundary; no API is started by these probes.
    from operations_backup_verify import run
    image = json.loads(run(['docker', 'image', 'inspect', context['new_image']]))[0]
    server = operations.source / 'server'
    require_verified_image(receipt, context, image, probe_image(context['new_image']),
        requirements_digest(no_links(server / 'requirements.txt').read_bytes()), expected_payload(server))
    api = json.loads(run(['docker', 'inspect', 'xiquan-api-1']))[0]
    if api['State']['Running'] or api['Image'] != context['old_api_image']:
        raise DeploymentError('Original API no longer remains stopped at this recovery point')
    operations.resolve_environment()
    if parse_environment(private_file(job / 'maintenance.env').read_text(encoding='utf-8')) != operations.env:
        raise DeploymentError('Maintenance environment changed; no credential or key rotation allowed')
    normal = dict(value.split('=', 1) for value in api['Config']['Env'] if '=' in value)
    if any(normal.get(key, '') != operations.normal_env.get(key, '') for key in
            ('SECRET_KEY', 'JWT_SECRET_KEY', 'AUDIT_HMAC_KEY', 'DATABASE_URL')):
        raise DeploymentError('Existing API runtime or signing identity changed')
    candidate = json_read(private_file(job / 'post-migration/candidate.json'))
    backup_receipt = json_read(private_file(job / 'post-migration/receipt.json'))
    rehearsal = json_read(private_file(job / 'rehearsal-verified.json'))
    # Apply uses the same evidence but the prepared preview is now a later phase.
    phase = latest_phase(job) if preparing else 'private-business-preview-nested'
    require_post_migration_checkpoint(phase, query_cloud_state(), rehearsal, backup_receipt,
        candidate, digest_file(private_file(job / 'post-migration/database.backup')))
    checks_name = 'preview-recovery-check-' + uuid.uuid4().hex + '.json'
    operations.inspect_current(checks_name)
    if json_read(job / checks_name) != candidate['checks']:
        raise DeploymentError('Current database differs from the verified post-migration snapshot; no apply')
    if (backup_receipt['restore']['source_server_id'] != candidate['checks']['server']['system_identifier']
            or (job / 'post-migration/database.backup').stat().st_size != candidate['dump_size']):
        raise DeploymentError('Verified backup physical source or size changed')
    return operations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--image-receipt', required=True)
    parser.add_argument('--mode', required=True, choices=['prepare', 'apply'])
    parser.add_argument('--preview-sha256')
    args = parser.parse_args()
    try:
        if os.name != 'posix' or os.getuid() != 0:
            raise DeploymentError('Run only as root on the existing ECS')
        if args.mode == 'apply' and not re.fullmatch('[0-9a-f]{64}', args.preview_sha256 or ''):
            raise DeploymentError('Apply requires the exact explicitly confirmed preview digest')
        with no_links('/run/lock/xiquan-operations-cutover.lock').open('r+') as handle:
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise DeploymentError('Another cutover is running; nothing was interrupted') from None
            operations = check_existing_job(args.stage, args.job, args.image_receipt, preparing=args.mode == 'prepare')
            print('VERIFIED_POST_MIGRATION_CHECKPOINT_NO_REBUILD_NO_MIGRATION', flush=True)
            if args.mode == 'prepare':
                preview = operations.preview()
                if not preview.get('can_apply'): raise DeploymentError('Private preview has business conflicts; no apply')
                operations.save_preview(preview)
            else:
                apply(operations, args.preview_sha256)
    except Exception as error:
        message = str(error) if isinstance(error, DeploymentError) else 'Preview recovery stopped; credentials were not printed'
        print('PREVIEW_RECOVERY_STOPPED: ' + message, file=sys.stderr)
        print('All backup evidence retained. No rebuild, migration, clearing or automatic rollback.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
