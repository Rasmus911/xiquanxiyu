[CmdletBinding()]
param(
    [ValidateSet('FinalStart')][string]$Checkpoint = 'FinalStart',
    [switch]$ApplyAfterPreview,
    [switch]$StageOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$commit = 'c468e73486c864fb732b6d09987d1d23cf222cfe'
$stage = '/opt/xiquan-releases/stock-stage-e983f550ba6d441b828ad8b54683946f'
$job = '/opt/xiquan-backups/stock-cutover-1b2ec99a92d041e5a846c1cf2c681592'
$bundle = Join-Path $root 'release\cloud\xiquan-stock-SOURCE-WEB-20261005-131735-9db6283a.zip'
$hash = '5d5545aa5f7c0586ecfedc87c987893e6c88b2f4ca0882fd6bc99d767e6a804a'
$helperHash = '4d900116afe6795e91a7b88da137a64082d7eca970b84333dd9854df935c7458'

# Local original bundle validation only; never invoke the old cloud resume.
& (Join-Path $root 'scripts\invoke-stock-upgrade.ps1') -Mode resume `
    -BundlePath $bundle -ExpectedSha256 $hash -SourceCommit $commit `
    -Stage $stage -Job $job -StageOnly | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Original local validation failed. Nothing uploaded.' }
$names = @('stock_deploy.py','stock_guard.py','operations_backup_verify.py',
    'operations_preflight.py','operations_deploy.py','operations_offline_build.py','stock_final_start.py')
$uploads = @()
foreach ($name in $names) {
    $path = Join-Path $root ('deploy\cloud\scripts\' + $name)
    $digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($name -eq 'stock_final_start.py' -and $digest -cne $helperHash) {
        throw 'Final-start helper bytes differ. Nothing uploaded.'
    }
    $uploads += [pscustomobject]@{Name=$name;Path=$path;Hash=$digest}
}
if ($StageOnly -or -not $ApplyAfterPreview) {
    Write-Host 'LOCAL_FINAL_START_VALIDATED. Cloud unchanged. Use -ApplyAfterPreview to start the existing verified API.'
    return
}
Write-Host 'FinalStart only: already released stock checkpoint; same existing API container; normal worker.'
Write-Host 'No build, migration, source switch, clearing, installer publication or cleanup.'
$target = 'root@39.96.217.210'
$options = @('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
$remote = '/tmp/xiquan-stock-final-start-' + [guid]::NewGuid().ToString('N')
& ssh.exe @options $target ('umask 077 && mkdir -m 700 ' + $remote)
if ($LASTEXITCODE -ne 0) { throw 'Transport creation failed. API was not started.' }
foreach ($item in $uploads) {
    & scp.exe @options -- $item.Path ($target + ':' + $remote + '/' + $item.Name)
    if ($LASTEXITCODE -ne 0) { throw 'Upload failed. API was not started.' }
}
$paths = @($uploads | ForEach-Object { $remote + '/' + $_.Name })
$remoteHashes = & ssh.exe @options $target ('sha256sum ' + ($paths -join ' '))
if ($LASTEXITCODE -ne 0) { throw 'Transport hash check failed. API was not started.' }
foreach ($item in $uploads) {
    $pattern = '^' + [regex]::Escape($item.Hash) + '\s+\*?' + [regex]::Escape($remote + '/' + $item.Name) + '$'
    if (@($remoteHashes | Where-Object { $_ -match $pattern }).Count -ne 1) {
        throw 'Remote helper/tool bytes differ. API was not started.'
    }
}
$command = 'python3 ' + $remote + '/stock_final_start.py final-start --commit ' + $commit +
    ' --stage ' + $stage + ' --job ' + $job
& ssh.exe @options $target $command
if ($LASTEXITCODE -ne 0) {
    throw ('FinalStart stopped. Preserve the actual phase/error; do not run old deployment scripts. Transport: ' + $remote)
}
Write-Host 'Final-start driver finished. Confirm STOCK_FINAL_START_OK, then sign in again.'
