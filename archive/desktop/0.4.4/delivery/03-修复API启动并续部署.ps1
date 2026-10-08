[CmdletBinding()]
param([switch]$StageOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$commit = 'c468e73486c864fb732b6d09987d1d23cf222cfe'
$stage = '/opt/xiquan-releases/stock-stage-e983f550ba6d441b828ad8b54683946f'
$job = '/opt/xiquan-backups/stock-cutover-1b2ec99a92d041e5a846c1cf2c681592'
$bundle = Join-Path $root 'release\cloud\xiquan-stock-SOURCE-WEB-20261005-131735-9db6283a.zip'
$hash = '5d5545aa5f7c0586ecfedc87c987893e6c88b2f4ca0882fd6bc99d767e6a804a'
$repairHash = 'a9731a82de2356d35aca2751d93310b3a5b1efe50a63b381aaf20ef2935ad5b9'

# Original six transport tools must still equal the original committed bundle.
# This performs only local validation and does NOT invoke cloud preflight/deploy.
& (Join-Path $root 'scripts\invoke-stock-upgrade.ps1') -Mode resume `
    -BundlePath $bundle -ExpectedSha256 $hash -SourceCommit $commit `
    -Stage $stage -Job $job -StageOnly | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Original local source validation failed. No cloud command invoked.' }
$names = @('stock_deploy.py','stock_guard.py','operations_backup_verify.py',
    'operations_preflight.py','operations_deploy.py','operations_offline_build.py','stock_startup_recovery.py')
$uploads = @()
foreach ($name in $names) {
    $path = Join-Path $root ('deploy\cloud\scripts\' + $name)
    $digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($name -eq 'stock_startup_recovery.py' -and $digest -cne $repairHash) {
        throw 'Startup recovery helper hash differs. Nothing uploaded.'
    }
    $uploads += [pscustomobject]@{Name=$name;Path=$path;Hash=$digest}
}
if ($StageOnly) {
    Write-Host 'LOCAL_RECOVERY_VALIDATED. Cloud unchanged; no restart, migration, restore or publication.'
    return
}
Write-Host 'Resume the existing ready checkpoint only. No rebuild, migration, clearing or rollback.'
Write-Host ('Checkpoint: ' + $job)
Write-Host 'Temporarily pause reset recovery during the owned stock maintenance; restore it after guarded release.'
$answer = Read-Host 'Type RESUME STOCK to continue'
if ($answer -cne 'RESUME STOCK') { throw 'Recovery not confirmed. No cloud command invoked.' }
$target = 'root@39.96.217.210'
$options = @('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
$remote = '/tmp/xiquan-stock-startup-recovery-' + [guid]::NewGuid().ToString('N')
& ssh.exe @options $target ('umask 077 && mkdir -m 700 ' + $remote)
if ($LASTEXITCODE -ne 0) { throw 'Transport directory creation failed. Recovery not invoked.' }
foreach ($item in $uploads) {
    & scp.exe @options -- $item.Path ($target + ':' + $remote + '/' + $item.Name)
    if ($LASTEXITCODE -ne 0) { throw 'Upload failed. Recovery not invoked.' }
}
$paths = @($uploads | ForEach-Object { $remote + '/' + $_.Name })
$remoteHashes = & ssh.exe @options $target ('sha256sum ' + ($paths -join ' '))
if ($LASTEXITCODE -ne 0) { throw 'Remote hash check failed. Recovery not invoked.' }
foreach ($item in $uploads) {
    $pattern = '^' + [regex]::Escape($item.Hash) + '\s+\*?' + [regex]::Escape($remote + '/' + $item.Name) + '$'
    if (@($remoteHashes | Where-Object { $_ -match $pattern }).Count -ne 1) {
        throw 'Remote helper/tool bytes differ. Recovery not invoked.'
    }
}
$command = 'python3 ' + $remote + '/stock_startup_recovery.py resume --commit ' + $commit +
    ' --stage ' + $stage + ' --job ' + $job
& ssh.exe @options $target $command
if ($LASTEXITCODE -ne 0) {
    throw ('Recovery stopped. Preserve checkpoint and output; do not rerun deploy or clear maintenance. Transport: ' + $remote)
}
Write-Host 'Recovery driver finished. Confirm STOCK_STARTUP_RECOVERY_OK in the output.'
