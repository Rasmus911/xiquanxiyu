# Public configuration checks only: no Docker, network, .env or database access.
[CmdletBinding()]
param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$code = @'
from pathlib import Path
import sys
import yaml
root = Path(sys.argv[1])
compose = yaml.safe_load((root / 'deploy/cloud/docker-compose.prod.yml').read_text(encoding='utf-8'))
api = compose['services']['api']; maint = compose['services']['maintenance']; nginx = compose['services']['nginx']
e = api['environment']
assert e['DATABASE_URL'] == e['RUNTIME_DATABASE_URL'] and ':?' in e['DATABASE_URL']
assert not any(k in e for k in ('MAINTENANCE_DATABASE_URL', 'POSTGRES_USER', 'POSTGRES_PASSWORD'))
assert all(':?' in e[k] for k in ('RESET_DATABASE_URL', 'RESET_BACKUP_DATABASE_URL'))
assert e['RUN_MIGRATIONS'] == e['SEED_DEFAULTS'] == e['AUTO_CREATE_DB'] == '0'
assert all(e[k] == '1' for k in ('API_WORKERS', 'WEB_CONCURRENCY', 'API_REPLICAS'))
assert maint['profiles'] == ['maintenance'] and maint['entrypoint'] == ['flask', '--app', 'run.py'] and maint['image'] == api['image']
assert api['volumes'] == ['reset_private:/var/lib/xiquan-reset']
assert not any('reset_private' in v or 'operations_private' in v for v in nginx['volumes'])
assert maint['volumes'] == ['operations_private:/var/lib/xiquan-operations']
assert not any('operations_private' in v for v in api['volumes'])
assert maint['environment']['MAINTENANCE_PROCESS'] == '1' and maint['environment']['RESET_WORKER_ENABLED'] == '0'
assert maint['environment']['SMS_ENABLED'] == '0'
assert e['PG_DUMP_PATH'] == '/usr/lib/postgresql/17/bin/pg_dump' and e['PG_RESTORE_PATH'] == '/usr/lib/postgresql/17/bin/pg_restore'
print('8 parsed Compose configuration checks passed (not Docker/PG runtime acceptance).')
'@
$code | & $Python - $root
if ($LASTEXITCODE -ne 0) { throw 'Public cloud configuration checks failed.' }
