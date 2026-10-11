[CmdletBinding()]
param([string]$EcsTarget = 'root@39.96.217.210', [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($EcsTarget -notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$') { throw 'Invalid SSH target.' }
$diagnostic = @'
import json
import re
import subprocess
from pathlib import Path

job = Path('/opt/xiquan-backups/desktop049-cutover-0612e87608b44f9991c797c0a1a76845')
failure = job / 'command-failure-ac1302f05f214ec2b025ab348f167557.json'

def checked(path):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise SystemExit('STOP: evidence path contains a symbolic link')
    return path

def safe_line(line):
    line = re.sub(r'[A-Za-z][A-Za-z0-9+.-]*://\S+', '[URL REDACTED]', line)
    line = re.sub(r'(?i)((?:password|passwd|secret|token|access.?key|authorization)\s*[=:]\s*)\S+', r'\1[REDACTED]', line)
    return line[:1200]

def errors_only(value):
    lines = str(value).splitlines()
    kept = []
    for line in lines:
        text = line.strip()
        if text.startswith(('[SQL:', '[parameters:', 'DETAIL:', 'CONTEXT:')):
            continue
        if (text.startswith(('Traceback ', 'File "', 'Error:', 'pg_dump:', 'pg_restore:', 'docker:', 'DESKTOP_GUARD_STOPPED:'))
                or re.search(r'(?:Error|Exception|Failure)(?:\([^)]*\))?:', text)):
            kept.append(safe_line(line))
    return '\n'.join(kept[-50:]) or 'NO_SAFE_ERROR_LINES; raw evidence remains private'

print('=== FAILED OWNER COMMAND ===')
record = json.loads(checked(failure).read_text(encoding='utf-8'))
print('EXIT_CODE:', record.get('exit_code'))
print(errors_only(record.get('stderr', '')))
print(errors_only(record.get('stdout', '')))

print('=== EXACT CHECKPOINT ===')
for name in ('before.json', 'after.json', 'ready.json', 'maintenance-released.json', 'completed.json'):
    path = checked(job / name)
    print(name, 'EXISTS' if path.exists() else 'MISSING')
context = json.loads(checked(job / 'context.json').read_text(encoding='utf-8'))
for name in ('stage', 'source_commit', 'image_id'):
    print(name + ':', context.get(name))
after = checked(job / 'after')
print('after directory:', 'EXISTS' if after.exists() else 'MISSING')
for name in ('database.backup', 'candidate.json', 'receipt.json'):
    path = checked(after / name)
    print('after/' + name, 'BYTES=' + str(path.stat().st_size) if path.is_file() else 'MISSING')

print('=== DATABASE READ ONLY ===')
sql = '''BEGIN READ ONLY;
SELECT json_build_object(
 'schema', (SELECT version_num FROM alembic_version),
 'maintenance', (SELECT maintenance FROM business_state WHERE id=1),
 'maintenance_owner', (SELECT maintenance_reset_id FROM business_state WHERE id=1));
SELECT c.relname AS registration_table,
 has_table_privilege('xiquan_backup', c.oid, 'SELECT') AS backup_can_read
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relname IN
 ('registration_token_state','registration_rate_limits','registration_receipts','registration_token_views')
ORDER BY c.relname;
ROLLBACK;'''
result = subprocess.run(['docker', 'exec', '-i', 'xiquan-postgres-1', 'sh', '-eu', '-c',
 'exec psql -X -P pager=off -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
 input=sql, text=True, capture_output=True, timeout=45)
print('DATABASE_QUERY_EXIT:', result.returncode)
if result.returncode:
    print(errors_only(result.stderr))
else:
    print(result.stdout.strip())
print('READ_ONLY_DIAGNOSTIC_FINISHED; no restart, migration, database change or evidence deletion')
if result.returncode:
    raise SystemExit(result.returncode)
'@
if ($ValidateOnly) {
    $diagnostic | & python.exe -c 'import ast,sys; ast.parse(sys.stdin.read()); print(True)'
    if ($LASTEXITCODE -ne 0) { throw 'Diagnostic syntax validation failed.' }
    return
}
$payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($diagnostic))
$remoteCommand = 'printf %s ' + $payload + ' | base64 -d | python3 -'
& ssh.exe -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 $EcsTarget $remoteCommand
if ($LASTEXITCODE -ne 0) { throw 'Read-only diagnostic incomplete. Keep the error output; do not rerun deployment.' }
