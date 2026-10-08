[CmdletBinding()]
param([string]$EcsTarget = 'root@39.96.217.210', [switch]$CheckOnly, [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($EcsTarget -notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$') { throw 'Invalid SSH target.' }
$helper = Join-Path $PSScriptRoot 'registration049_backup_recovery.py'
if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'Recovery helper missing.' }
if ($ValidateOnly) {
    Get-Content -LiteralPath $helper -Raw -Encoding UTF8 | & python.exe -c 'import ast,sys; ast.parse(sys.stdin.read()); print(True)'
    if ($LASTEXITCODE -ne 0) { throw 'Recovery syntax check failed.' }
    return
}
if (-not $CheckOnly) {
    Write-Host 'Checks the exact checkpoint and all role invariants first. Grants missing SELECT only on the new registration sequence.'
    Write-Host 'Only the existing app/reset/backup roles can receive this object-specific read grant; no role or password changes.'
    Write-Host 'Retains the zero-byte failed backup; resumes without rebuilding, rerunning migration or clearing business data.'
    if ((Read-Host 'Type FIX BACKUP 0.4.9') -cne 'FIX BACKUP 0.4.9') { throw 'Cancelled. No connection attempted.' }
}
$hash = (Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash.ToLowerInvariant()
$options = @('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
$remote = '/tmp/xiquan-registration049-backup-recovery-' + [guid]::NewGuid().ToString('N')
& ssh.exe @options $EcsTarget ('umask 077 && mkdir -m 700 ' + $remote)
if ($LASTEXITCODE -ne 0) { throw 'Private transport creation failed. No repair started.' }
& scp.exe @options -- $helper ($EcsTarget + ':' + $remote + '/recover.py')
if ($LASTEXITCODE -ne 0) { throw 'Recovery helper upload failed. No repair started.' }
$actual = & ssh.exe @options $EcsTarget ('sha256sum ' + $remote + '/recover.py')
if ($LASTEXITCODE -ne 0 -or @($actual).Count -ne 1 -or $actual -notmatch ('^' + $hash + '\s')) {
    throw 'Remote helper hash mismatch. No repair started.'
}
$command = 'python3 ' + $remote + '/recover.py'
if (-not $CheckOnly) { $command += ' --apply' }
& ssh.exe @options $EcsTarget $command
if ($LASTEXITCODE -ne 0) { throw 'Recovery stopped. Preserve the job and output; do not rerun deploy or clear maintenance.' }
if ($CheckOnly) { Write-Host 'Check completed. No repair or service start performed.' }
else { Write-Host 'Cloud recovery completed. Test existing login/data before desktop or Android publication.' }
