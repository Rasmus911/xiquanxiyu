"""User-run SOURCE/WEB staging and READ-ONLY cloud preflight, not a cutover tool.

Deliberately has no apply mode: restoring a historical dump does not authorize
schema migration or replacement of live financial data. No secrets are printed.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath


class PreflightError(ValueError):
    pass


REQUIRED = {'server/app/operations_backup.py', 'server/app/operations_upgrade.py',
    'server/app/catalog_defaults.py', 'server/app/__init__.py', 'server/Dockerfile',
    'deploy/cloud/docker-compose.prod.yml', 'client/dist/index.html', 'mobile/dist/index.html'}
APPROVED_ADMINS = {
    '9ff0ec9e-47ac-4ef3-857b-0412336f50f4': '18631459666',
    '5349fd2e-6aa5-4677-bbc7-c1d220d16276': '18603346509',
    'f8179cc6-63c3-455e-88a8-77056b52f136': '15133863898',
}


def no_links(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise PreflightError('Parent traversal is forbidden')
    for item in [*path.parents, path]:
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise PreflightError('Linked storage paths are forbidden')
    return path


def digest_file(path):
    path = no_links(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        after = os.fstat(stream.fileno())
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise PreflightError('File changed during validation')
    return digest.hexdigest()


def safe_relative(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise PreflightError('Unsafe archive path')
    parts = name.split('/')
    if any(part in ('', '.', '..', 'private', '.venv', 'node_modules', '.git') for part in parts):
        raise PreflightError('Private or unsafe archive path')
    if any(part.startswith('.env') and part != '.env.example' for part in parts):
        raise PreflightError('Production configuration is forbidden in SOURCE/WEB')
    if (name.endswith(('.pem', '.key', '.jks', '.keystore', '.pfx', '.p12', '.exe', '.apk'))
            or name == 'deploy/cloud/nginx/active.conf'
            or any(name.startswith(prefix) for prefix in (
                'deploy/cloud/updates/', 'deploy/cloud/releases/', 'deploy/cloud/mobile/downloads/'))):
        raise PreflightError('Keys, installers and live update feeds are forbidden')
    return PurePosixPath(name)


def stage_bundle(archive, expected_sha256, stage=None):
    """Validate every ZIP byte and manifest BEFORE creating any staging directory."""
    archive = no_links(archive)
    stage = no_links(stage) if stage is not None else None
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256) or digest_file(archive) != expected_sha256:
        raise PreflightError('SOURCE/WEB SHA256 mismatch')
    if stage is not None and stage.exists():
        raise PreflightError('Existing stage must not be overwritten')
    try:
        with zipfile.ZipFile(archive) as source:
            entries = {}
            for entry in source.infolist():
                safe_relative(entry.filename)
                if (entry.filename in entries or not entry.filename.startswith('xiquan/')
                        or entry.is_dir() or entry.flag_bits & 1
                        or stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK
                        or entry.file_size > 32 * 1024 * 1024):
                    raise PreflightError('Duplicate, linked, encrypted or oversized ZIP entry')
                safe_relative(entry.filename[len('xiquan/'):])
                entries[entry.filename] = entry
            if sum(entry.file_size for entry in entries.values()) > 200 * 1024 * 1024:
                raise PreflightError('SOURCE/WEB uncompressed size exceeds limit')
            manifest_entry = entries.get('xiquan/source-manifest.json')
            if not manifest_entry or manifest_entry.file_size > 2 * 1024 * 1024:
                raise PreflightError('Reviewed source manifest missing or oversized')
            manifest = json.loads(source.read(manifest_entry).decode('utf-8-sig'))
            if (manifest.get('schema') != 1 or manifest.get('label') != 'SOURCE/WEB'
                    or not re.fullmatch('[0-9a-f]{40}', str(manifest.get('source_commit', '')))):
                raise PreflightError('Invalid SOURCE/WEB identity')
            records = {}
            for record in manifest['files']:
                name = record['file']
                safe_relative(name)
                if (name in records or type(record['size']) is not int or record['size'] < 0
                        or not re.fullmatch('[0-9a-f]{64}', record['sha256'])):
                    raise PreflightError('Invalid or repeated source record')
                records[name] = record
            if not REQUIRED.issubset(records):
                raise PreflightError('Required operational source is missing')
            metadata = {'xiquan/source-manifest.json', 'xiquan/SOURCE-WEB-NOT-PRODUCTION.txt'}
            if set(entries) != {'xiquan/' + name for name in records} | metadata:
                raise PreflightError('ZIP entries differ from the reviewed manifest')
            for name, record in records.items():
                entry = entries['xiquan/' + name]
                if entry.file_size != record['size']:
                    raise PreflightError('Source file size mismatch')
                digest = hashlib.sha256()
                with source.open(entry) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                if digest.hexdigest() != record['sha256']:
                    raise PreflightError('Source file SHA256 mismatch')
            if digest_file(archive) != expected_sha256:
                raise PreflightError('Archive changed during validation')
            if stage is None:
                return dict(source_commit=manifest['source_commit'], file_count=len(records),
                            bundle_sha256=expected_sha256, stage_directory=None)
            if shutil.disk_usage(stage.parent).free < sum(e.file_size for e in entries.values()) + 1024**3:
                raise PreflightError('Insufficient disk space for private staging')
            stage.mkdir(mode=0o700)
            for name, entry in entries.items():
                target = stage.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with source.open(entry) as reader, target.open('xb') as writer:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
                if os.name == 'posix': target.chmod(0o600)
                relative = name[len('xiquan/'):]
                if relative in records and digest_file(target) != records[relative]['sha256']:
                    raise PreflightError('Staged source changed; leave evidence for inspection')
    except PreflightError:
        raise
    except Exception:
        raise PreflightError('SOURCE/WEB validation failed; no live files were replaced') from None
    return dict(source_commit=manifest['source_commit'], file_count=len(records),
                bundle_sha256=expected_sha256, stage_directory=str(stage))


def check_private_configuration(env_path):
    path = no_links(env_path)
    if not path.is_file():
        raise PreflightError('Existing private .env is missing; no default credentials will be created')
    contents = path.read_text(encoding='utf-8-sig')
    missing = [name for name in ('MAINTENANCE_DATABASE_URL', 'RUNTIME_DATABASE_URL',
        'RESET_DATABASE_URL', 'RESET_BACKUP_DATABASE_URL')
        if not re.search(r'^' + name + r'=\S.+$', contents, re.MULTILINE)]
    if missing:
        raise PreflightError('Missing private configuration: ' + ', '.join(missing))


def command_json(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=60)
        return json.loads(result.stdout)
    except Exception:
        raise PreflightError('Read-only cloud command failed; raw configuration and credentials were not printed') from None


def protected_files(cloud):
    result = {}
    targets = [cloud / 'nginx/active.conf', cloud / 'mobile/download-config.json']
    for name in ('updates', 'releases', 'mobile/downloads'):
        directory = no_links(cloud / name)
        if directory.is_dir():
            for parent, dirs, files in os.walk(directory, followlinks=False):
                for item in dirs:
                    no_links(Path(parent) / item)
                targets.extend(Path(parent) / item for item in files)
    for path in targets:
        path = no_links(path)
        if not path.exists(): continue
        if not path.is_file(): raise PreflightError('Protected release reference is not a regular file')
        info = path.stat()
        result[str(path.relative_to(cloud))] = dict(sha256=digest_file(path), size=info.st_size,
            inode=info.st_ino, device=info.st_dev)
    if 'nginx/active.conf' not in result:
        raise PreflightError('Existing nginx active.conf must be preserved and is missing')
    return result


READ_ONLY_SQL = """BEGIN READ ONLY;
SELECT json_build_object(
 'schema_revision',(SELECT version_num FROM alembic_version),
 'pg_major',current_setting('server_version_num')::integer/10000,
 'business_state',(SELECT json_build_object('period_id',period_id,'business_revision',business_revision,
                      'maintenance',maintenance,'policy_version',policy_version) FROM business_state WHERE id=1),
 'active_policy',(SELECT json_build_object('owner_id',owner_id,'mobile_employee_ids',mobile_employee_ids,
                      'administrator_employee_ids',administrator_employee_ids,'policy_version',policy_version)
                      FROM access_policies WHERE is_active),
 'administrators',(SELECT json_agg(json_build_object('id',id,'username',username,'role',role,'is_active',is_active))
                      FROM employees WHERE role='admin'),
 'open_visits',(SELECT count(*) FROM visits WHERE status IN ('open','settling')),
 'unresolved_wristbands',(SELECT json_agg(number ORDER BY number) FROM wristbands WHERE status<>'available'),
 'pending_resets',(SELECT count(*) FROM reset_tasks WHERE status IN ('queued','running')),
 'audit_rows',(SELECT count(*) FROM audit_logs)
);
ROLLBACK;"""


def query_cloud_state():
    # psql -q suppresses BEGIN/ROLLBACK command tags so stdout remains one JSON value.
    shell = 'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"'
    return command_json(['docker', 'exec', 'xiquan-postgres-1', 'sh', '-eu', '-c', shell, 'sh', READ_ONLY_SQL])


def cloud_preflight(archive, expected_sha256):
    if os.name != 'posix' or os.getuid() != 0:
        raise PreflightError('Run this preflight as root on the existing ECS, not on Windows')
    cloud = no_links('/opt/xiquan/xiquan/deploy/cloud')
    check_private_configuration(cloud / '.env')
    no_links(cloud / 'docker-compose.prod.yml')
    # Read only selected SQL fields. Password hashes and URLs never enter this report.
    report = query_cloud_state()
    if report['pg_major'] != 17:
        raise PreflightError('The actual production database must be PostgreSQL 17')
    if report['schema_revision'] not in {'20261003_preserve_administrators',
        '20261004_employee_entries', '20261004_catalog_packages'}:
        raise PreflightError('Unexpected cloud schema revision; do not guess a migration chain')
    images = command_json(['docker', 'inspect', 'xiquan-api-1', 'xiquan-nginx-1', 'xiquan-postgres-1'])
    single_api = command_json(['docker', 'ps', '--filter', 'label=com.docker.compose.project=xiquan',
        '--filter', 'label=com.docker.compose.service=api', '--format', '{{json .}}'])
    if not isinstance(single_api, dict) or not images[0]['Id'].startswith(single_api.get('ID', 'NO_API')):
        raise PreflightError('One actual running compose API container is required')
    containers = {}
    for item in images:
        if item['State'].get('Health', {}).get('Status') != 'healthy' or not item['State'].get('Running'):
            raise PreflightError('Existing production containers must be healthy before staging')
        variables = dict(value.split('=', 1) for value in item['Config'].get('Env', []) if '=' in value)
        for name in ('API_WORKERS', 'WEB_CONCURRENCY', 'API_REPLICAS'):
            if variables.get(name, '1') != '1':
                raise PreflightError('Only one API worker and one replica are supported')
        containers[item['Name'].lstrip('/')] = dict(image_id=item['Image'], container_id=item['Id'])
    policy = report.get('active_policy')
    if not policy or policy['policy_version'] != report['business_state']['policy_version']:
        raise PreflightError('Active access policy does not match business state')
    highest = {str(policy['owner_id']), *policy['mobile_employee_ids'], *policy['administrator_employee_ids']}
    rows = {str(row['id']): row for row in report.get('administrators') or []}
    report['mobile_administrator_checks'] = []
    for identity, username in APPROVED_ADMINS.items():
        row = rows.get(identity)
        report['mobile_administrator_checks'].append(dict(id=identity, username=username,
            identity_matches=bool(row and row['username'] == username),
            active=bool(row and row['is_active']), highest_binding=identity in highest))
    protected = protected_files(cloud)
    release_root = no_links('/opt/xiquan-releases')
    release_root.mkdir(mode=0o700, exist_ok=True)
    if release_root.stat().st_uid != 0 or stat.S_IMODE(release_root.stat().st_mode) & 0o077:
        raise PreflightError('Existing release staging root must be root-owned and private')
    stage = release_root / ('operations-stage-' + uuid.uuid4().hex)
    identity = stage_bundle(archive, expected_sha256, stage)
    report.update(identity, protected_references=protected, containers=containers,
        stage_only=True, schema_migrated=False, business_data_replaced=False, cutover_authorized=False)
    output = stage / 'preflight-report.json'
    with output.open('x', encoding='utf-8') as writer:
        json.dump(report, writer, ensure_ascii=False, indent=2)
    output.chmod(0o600)
    print(json.dumps(dict(report_path=str(output), source_commit=identity['source_commit'],
        stage_directory=str(stage), schema_revision=report['schema_revision'],
        open_visits=report['open_visits'], unresolved_wristbands=report['unresolved_wristbands'],
        pending_resets=report['pending_resets'], mobile_administrator_checks=report['mobile_administrator_checks'],
        protected_file_count=len(protected), stage_only=True), ensure_ascii=False, indent=2))
    print('SOURCE_STAGE_AND_READONLY_PREFLIGHT_OK')
    print('No API stop, migration, business replacement, installer publication or cleanup was performed.')


def main():
    parser = argparse.ArgumentParser(description='Private SOURCE/WEB staging; read-only preflight ONLY')
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--mode', choices=['preflight'], default='preflight')
    parser.add_argument('--local-check', action='store_true', help='Validate ZIP bytes only, no network or writes')
    args = parser.parse_args()
    try:
        if args.local_check:
            print(json.dumps(stage_bundle(args.bundle, args.expected_sha256)))
        else:
            cloud_preflight(args.bundle, args.expected_sha256)
    except Exception as error:
        message = str(error) if isinstance(error, PreflightError) else 'Preflight stopped; live data was not changed'
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
