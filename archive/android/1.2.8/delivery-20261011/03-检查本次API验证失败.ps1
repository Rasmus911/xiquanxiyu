[CmdletBinding()]
param([string]$EcsTarget = 'root@39.96.217.210', [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
if ($EcsTarget -notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$') { throw 'Invalid SSH target.' }
$program = @'
import json, re, subprocess
from pathlib import Path

job = Path('/opt/xiquan-backups/registration-token128-b5f7a92d205346528b0024a16827df7f')

def run(args):
    try:
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        print('READ_COMMAND_TIMEOUT')
        return None

def safe_errors(value):
    result = []
    for line in str(value).splitlines():
        if re.search(r'(?i)password|secret|access.?key|authorization|bearer|://[^\s]*@|\btoken\s*[:=]', line):
            continue
        if re.search(r'(?i)^nginx:|^curl:|\[emerg\]|^Error response from daemon:|^Error:|[A-Za-z]+Error:|permission denied|host not found in upstream', line):
            result.append(line[:350])
    return result[-12:]

print('=== EXACT PRIVATE CHECKPOINT ===')
if not job.is_dir() or job.is_symlink():
    raise SystemExit('PRIVATE_JOB_NOT_FOUND')
ready = {}
for name in ('ready.json', 'completed.json', 'original-api-restored.json'):
    path = job / name
    print(name, 'EXISTS' if path.is_file() else 'MISSING')
    if name == 'ready.json' and path.is_file():
        ready = json.loads(path.read_text())

print('\n=== RETAINED COMMAND FAILURE ===')
evidence = sorted(job.glob('command-failure-*.json'), key=lambda p:p.stat().st_mtime)
print('FAILURE_FILE_COUNT:', len(evidence))
for path in evidence[-4:]:
    if path.is_symlink():
        continue
    record = json.loads(path.read_text())
    print('EVIDENCE_FILE:', path.name)
    print('EXIT_CODE:', record.get('exit'))
    lines = safe_errors(str(record.get('stdout','')) + '\n' + str(record.get('stderr','')))
    print('\n'.join(lines) if lines else 'NO_SAFE_ERROR_LINES; raw evidence remains private')

print('\n=== CURRENT API STATE ===')
inspected = run(['docker','inspect','xiquan-api-1'])
if inspected is not None and inspected.returncode == 0:
    api = json.loads(inspected.stdout)[0]
    state = api['State']
    print(json.dumps({'status':state.get('Status'), 'health':state.get('Health',{}).get('Status'),
        'exit_code':state.get('ExitCode'), 'oom':state.get('OOMKilled'),
        'original_image_active':api['Image'] == ready.get('old_image')}, indent=2))
    candidate = job / 'candidate-stack.json'
    if candidate.is_file() and not candidate.is_symlink():
        compared = run(['docker','compose','--project-directory','/opt/xiquan/xiquan/deploy/cloud',
            '-p','xiquan','-f',str(candidate),'config','--format','json'])
        image = run(['docker','image','inspect',str(ready.get('new_image',''))])
        if compared is not None and image is not None and compared.returncode == 0 and image.returncode == 0:
            config = json.loads(compared.stdout)['services']['api']
            defaults = json.loads(image.stdout)[0]['Config']
            expected = dict(v.split('=',1) for v in defaults.get('Env',[]))
            expected.update({k:str(v) for k,v in config.get('environment',{}).items()})
            current = dict(v.split('=',1) for v in api['Config'].get('Env',[]))
            changes = sorted(k for k in set(expected)|set(current) if expected.get(k) != current.get(k))
            print('CANDIDATE_ENV_DIFFERING_NAMES_ONLY:', json.dumps(changes))
            print('CANDIDATE_PROCESS_DIFFERS:', any(
                (config.get(c) if config.get(c) is not None else defaults.get(d)) != api['Config'].get(d)
                for c,d in [('command','Cmd'),('entrypoint','Entrypoint'),('user','User'),('working_dir','WorkingDir')]))

print('\n=== NGINX CHECK ===')
nginx = run(['docker','exec','xiquan-nginx-1','nginx','-t'])
if nginx is not None:
    print('NGINX_EXIT:', nginx.returncode)
    print('\n'.join(safe_errors(nginx.stderr)) if nginx.returncode else 'NGINX_CONFIG_OK')

print('\n=== DIRECT ORIGIN HEALTH ===')
health = run(['curl','--silent','--show-error','--max-time','15',
    '--resolve','api.pqxqxy.xyz:443:127.0.0.1','--noproxy','api.pqxqxy.xyz',
    '--output','/dev/null','--write-out','HTTP=%{http_code}\n','https://api.pqxqxy.xyz/api/health'])
if health is not None:
    print('CURL_EXIT:', health.returncode)
    print(health.stdout.strip())
    print('\n'.join(safe_errors(health.stderr)))
print('READ_ONLY_TOKEN_DIAGNOSTIC_FINISHED; no restart or database changes')
'@
if ($ValidateOnly) { $program; return }
. 'F:\溪泉洗浴系统\scripts\lib\mobile-128-transport.ps1'
$options = @('-T','-o','BatchMode=yes','-o','ConnectionAttempts=1','-o','ConnectTimeout=15',
    '-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2',$EcsTarget,'python3 -')
Write-Host '只读检查本次失败证据，不更新、不重启、不修改数据库。'
$result = Invoke-TokenNative -Executable 'ssh.exe' -Arguments $options -InputText ($program + "`n") `
    -TimeoutSeconds 150 -Label 'READ_ONLY_TOKEN_DIAGNOSTIC'
if ($result.Stdout) { Write-Host $result.Stdout }
if ($result.ExitCode -ne 0) { throw ('只读检查未完成：' + $result.Stderr.Trim()) }
