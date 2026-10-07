#!/usr/bin/env bash
# Sent over SSH by upload-security-upgrade.ps1; do not run against a test path.
set -Eeuo pipefail
umask 077

archive="${1:?release ZIP required}"
expected_hash="${2:?SHA256 required}"
run_id="${3:?run ID required}"
project='/opt/xiquan/xiquan'
cloud="$project/deploy/cloud"
release_root='/opt/xiquan-releases'
backup_root='/opt/xiquan-backups'

[[ "$run_id" =~ ^[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$ ]] || { echo 'Invalid release ID.' >&2; exit 1; }
[[ "$expected_hash" =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid release hash.' >&2; exit 1; }
[[ "$archive" == "$release_root/$run_id.zip" ]] || { echo 'Unexpected release path.' >&2; exit 1; }
[[ "$(realpath -e "$project")" == "$project" ]] || { echo 'Project path must not be a symlink.' >&2; exit 1; }
[[ "$(realpath -e "$cloud")" == "$cloud" ]] || { echo 'Cloud path must not be a symlink.' >&2; exit 1; }
for command in docker python3 curl tar sha256sum flock realpath; do
  command -v "$command" >/dev/null || { echo "Required command missing: $command" >&2; exit 1; }
done
[[ -f "$cloud/.env" && -f "$cloud/docker-compose.prod.yml" ]] || { echo 'Existing deployment/.env is missing.' >&2; exit 1; }
[[ ! -L "$release_root" && ! -L "$backup_root" ]] || { echo 'Dedicated release/backup directories must not be symlinks.' >&2; exit 1; }
install -d -m 0700 "$release_root" "$backup_root"
exec 9>"$release_root/deploy.lock"
flock -n 9 || { echo 'Another deployment is running. Do not start a second upload.' >&2; exit 1; }

actual_hash="$(sha256sum "$archive" | cut -d ' ' -f 1)"
[[ "$actual_hash" == "$expected_hash" ]] || { echo 'Uploaded ZIP hash mismatch; no running service was changed.' >&2; exit 1; }
stage="$release_root/stage-$run_id"
backup="$backup_root/release-$run_id"
[[ ! -e "$stage" && ! -e "$backup" ]] || { echo 'Release ID already exists; do not overwrite a previous attempt.' >&2; exit 1; }
mkdir -m 0700 "$stage" "$backup"

# common.sh sources the existing private .env without displaying its values.
source "$cloud/scripts/common.sh"
load_env
validate_settings
[[ "$API_DOMAIN" == 'api.pqxqxy.xyz' ]] || { echo 'Existing API_DOMAIN does not match this release.' >&2; exit 1; }
compose version >/dev/null
compose exec -T --interactive=false postgres pg_isready --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" >/dev/null
if [[ -n "${RUNTIME_DATABASE_URL:-}" ]]; then
  [[ "$RUNTIME_DATABASE_URL" == postgresql+psycopg://xiquan_app:* ]] || {
    echo 'This release grant script requires the dedicated xiquan_app runtime role. See the security release guide.' >&2
    exit 1
  }
else
  echo 'WARNING: RUNTIME_DATABASE_URL is not configured; minimum-privilege DB hardening is NOT complete.' >&2
fi

maintenance=0
files_changed=0
on_failure() {
  code=$?
  trap - ERR
  echo "Deployment stopped (exit $code). Backup directory: $backup" >&2
  if [[ "$maintenance" == 1 && "$files_changed" == 0 ]]; then
    echo 'No files or database schema were changed; attempting to restart existing containers.' >&2
    compose start api nginx || true
  elif [[ "$files_changed" == 1 ]]; then
    echo 'New code/migrations may be present. Do NOT blindly roll back the old API or restore the database.' >&2
    echo "Inspect: cd $cloud; docker compose --env-file .env -f docker-compose.prod.yml logs --tail=120 api nginx" >&2
  fi
  exit "$code"
}
trap on_failure ERR

echo '[1/7] Validate and extract the uploaded release into an isolated staging directory...'
python3 - "$archive" "$stage" <<'PY'
import pathlib
import shutil
import sys
import zipfile

archive, stage = sys.argv[1:]
root = pathlib.Path(stage).resolve()
with zipfile.ZipFile(archive) as bundle:
    seen = set()
    entries = bundle.infolist()
    required_space = sum(entry.file_size for entry in entries) + 1024**3
    if shutil.disk_usage(root).free < required_space:
        raise SystemExit('Insufficient free disk space to stage the release safely.')
    for entry in entries:
        name = entry.filename.replace('\\', '/')
        parts = pathlib.PurePosixPath(name).parts
        if not parts or parts[0] != 'xiquan' or ':' in name or '..' in parts or name in seen:
            raise SystemExit('Unsafe or duplicate ZIP path: ' + name)
        seen.add(name)
        if any(part in ('private', '.venv', 'node_modules', '.env') for part in parts):
            raise SystemExit('Private ZIP path is forbidden: ' + name)
        if name.lower().endswith(('.jks', '.keystore', '.pem', '.key')) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
            raise SystemExit('Private key or ZIP symlink is forbidden: ' + name)
        target = root.joinpath(*parts)
        if entry.is_dir() or name.endswith('/'):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with bundle.open(entry) as source, target.open('xb') as destination:
            shutil.copyfileobj(source, destination, 1024 * 1024)
PY

staged_cloud="$stage/xiquan/deploy/cloud"
staged_compose() {
  docker compose --env-file "$cloud/.env" -f "$staged_cloud/docker-compose.prod.yml" "$@"
}
echo '[2/7] Build and validate the new API before stopping the existing services...'
staged_compose build --pull api
staged_compose run -T --interactive=false --rm --no-deps -e AUTO_CREATE_DB=0 --entrypoint python api \
  -c 'from app import create_app; create_app(); print("Production configuration check passed; no migrations were run.")'

echo '[3/7] Preserve existing code, configuration and private .env...'
backup_items=(deploy/cloud server/app server/migrations)
for file in Dockerfile .dockerignore docker-entrypoint.sh requirements.txt run.py; do
  if [[ -e "$project/server/$file" ]]; then backup_items+=("server/$file"); fi
done
tar -czf "$backup/deployment-before.tar.gz" -C "$project" "${backup_items[@]}"
tar -tzf "$backup/deployment-before.tar.gz" >/dev/null
sha256sum "$backup/deployment-before.tar.gz" > "$backup/deployment-before.tar.gz.sha256"
api_id="$(compose ps -q api)"
if [[ -n "$api_id" ]]; then docker inspect --format '{{.Image}}' "$api_id" > "$backup/api-image-id.txt"; fi

echo '[4/7] Enter maintenance and make a verified PostgreSQL backup...'
maintenance=1
compose stop nginx api
compose exec -T --interactive=false postgres pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --format=custom --no-owner > "$backup/database.dump"
compose exec -T postgres pg_restore --list < "$backup/database.dump" >/dev/null
sha256sum "$backup/database.dump" > "$backup/database.dump.sha256"

echo '[5/7] Install staged files without replacing .env or deleting Docker data volumes...'
files_changed=1
cp -a "$stage/xiquan/." "$project/"
for public_dir in web mobile updates releases; do
  find "$cloud/$public_dir" -type d -exec chmod 0755 {} +
  find "$cloud/$public_dir" -type f -exec chmod 0644 {} +
done
source "$cloud/scripts/common.sh"
load_env
validate_settings
render_nginx https

echo '[6/7] Apply migrations, grant the configured runtime role, and restart API/Nginx...'
compose run -T --interactive=false --rm --no-deps --entrypoint flask api --app run.py db upgrade
if [[ -n "${RUNTIME_DATABASE_URL:-}" ]]; then
  compose exec -T postgres psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    < "$cloud/scripts/runtime-role.sql"
fi
compose up -d --force-recreate api nginx
if ! wait_for_api 'https://api.pqxqxy.xyz/api/health' '' 48; then
  echo 'API health check failed. Existing backup remains intact.' >&2
  false
fi
compose exec -T --interactive=false nginx nginx -t
head_revision="$(compose exec -T --interactive=false postgres psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -Atc 'SELECT version_num FROM alembic_version;')"
[[ "$head_revision" == '20260930_security_evidence' ]] || { echo 'Database migration head is incorrect.' >&2; false; }

echo '[7/7] Verify installed release hashes and public version manifests...'
python3 - "$cloud" <<'PY'
import hashlib
import json
import pathlib
import sys
import urllib.request

cloud = pathlib.Path(sys.argv[1])
policy = json.loads((cloud / 'releases/client-policy.json').read_text(encoding='utf-8-sig'))
for platform, relative in (
    ('desktop', 'updates/Xiquan-Bathhouse-Setup-0.4.0.exe'),
    ('android', 'mobile/downloads/xiquan-mobile-ordering-1.2.0.apk'),
):
    digest = hashlib.sha256()
    with (cloud / relative).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != policy[platform]['sha256']:
        raise SystemExit('Installed file checksum mismatch: ' + relative)
base = 'https://api.pqxqxy.xyz'
def public_json(path):
    with urllib.request.urlopen(base + path, timeout=30) as response:
        return json.load(response)
public = public_json('/releases/client-policy.json')
if public != policy:
    raise SystemExit('Public release policy does not match the installed policy.')
if public_json('/app/version.json')['buildId'] != '20260930-security-040':
    raise SystemExit('Public web build ID is incorrect.')
if public_json('/mobile/download-config.json')['versionCode'] != 7:
    raise SystemExit('Public mobile download configuration is incorrect.')
for path in ('/mobile/download', '/updates/latest.yml', '/updates/Xiquan-Bathhouse-Setup-0.4.0.exe', '/mobile/downloads/xiquan-mobile-ordering-1.2.0.apk'):
    request = urllib.request.Request(base + path, method='HEAD')
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise SystemExit('Published download is not available: ' + path)
print('API, database revision, release manifests and download endpoints verified.')
PY
compose ps
trap - ERR
echo "Deployment complete. Backup retained: $backup"
echo 'All employees must log in again. Verify a small test transaction and USB printing before resuming business.'
echo 'Copy backups/evidence to an independent secure location. No old backup or data volume was deleted.'

