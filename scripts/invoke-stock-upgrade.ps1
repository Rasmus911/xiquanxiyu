[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('preflight','deploy','resume')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$BundlePath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$SourceCommit,
    [string]$Stage,
    [string]$Job,
    [switch]$StageOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bundle = (Resolve-Path -LiteralPath $BundlePath).Path
if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha256) { throw 'SOURCE SHA256 differs.' }
$raw = & node.exe (Join-Path $PSScriptRoot 'lib\stock-source.cjs') archive $bundle $SourceCommit
if ($LASTEXITCODE -ne 0) { throw 'Committed stock SOURCE validation failed.' }
$manifest = ($raw -join "`n") | ConvertFrom-Json
$names = @('stock_deploy.py','stock_guard.py','operations_backup_verify.py','operations_preflight.py','operations_deploy.py','operations_offline_build.py')
$tools = @()
foreach ($name in $names) {
    $file = Join-Path $root ('deploy\cloud\scripts\' + $name)
    $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    $record = @($manifest.files | Where-Object { $_.file -eq ('deploy/cloud/scripts/' + $name) })
    if ($record.Count -ne 1 -or $record[0].sha256 -ne $hash) { throw ('Tool differs from SOURCE: ' + $name) }
    $tools += [pscustomobject]@{Name=$name;File=$file;Hash=$hash}
}
if ($Mode -ne 'preflight' -and $Stage -notmatch '^/opt/xiquan-releases/stock-stage-[0-9a-f]{32}$') { throw 'Exact stock stage path required.' }
if ($Mode -eq 'resume' -and $Job -notmatch '^/opt/xiquan-backups/stock-cutover-[0-9a-f]{32}$') { throw 'Exact stock job path required.' }
if ($StageOnly) {
    [pscustomobject]@{Mode=$Mode;SourceCommit=$SourceCommit;Sha256=$ExpectedSha256;StageOnly=$true;CloudChanged=$false}
    return
}
if ($Mode -ne 'preflight') {
    $confirmation = Read-Host ('Stop API writes for stock maintenance. Type MAINTENANCE ' + $SourceCommit)
    if ($confirmation -cne ('MAINTENANCE ' + $SourceCommit)) { throw 'Maintenance not confirmed.' }
}
$target = 'root@39.96.217.210'
$remote = '/tmp/xiquan-stock-tools-' + [guid]::NewGuid().ToString('N')
$options = @('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
& ssh.exe @options $target ('umask 077 && mkdir -m 700 ' + $remote)
if ($LASTEXITCODE -ne 0) { throw 'Private upload directory creation failed.' }
$uploads = @($tools | ForEach-Object { [pscustomobject]@{File=$_.File;Hash=$_.Hash;Remote=($remote + '/' + $_.Name)} })
if ($Mode -eq 'preflight') {
    $uploads += [pscustomobject]@{File=$bundle;Hash=$ExpectedSha256;Remote=($remote + '/source.zip')}
}
foreach ($item in $uploads) {
    & scp.exe @options -- $item.File ($target + ':' + $item.Remote)
    if ($LASTEXITCODE -ne 0) { throw 'Upload failed. Driver was not invoked; retained upload evidence.' }
}
$hashes = & ssh.exe @options $target ('sha256sum ' + (($uploads | ForEach-Object { $_.Remote }) -join ' '))
if ($LASTEXITCODE -ne 0) { throw 'Remote hash command failed. Driver was not invoked.' }
foreach ($item in $uploads) {
    $pattern = '^' + [regex]::Escape($item.Hash) + '\s+\*?' + [regex]::Escape($item.Remote) + '$'
    if (@($hashes | Where-Object { $_ -match $pattern }).Count -ne 1) { throw 'Remote hash mismatch. Driver was not invoked.' }
}
$command = 'python3 ' + $remote + '/stock_deploy.py ' + $Mode + ' --commit ' + $SourceCommit
if ($Mode -eq 'preflight') { $command += ' --bundle ' + $remote + '/source.zip --sha256 ' + $ExpectedSha256 }
else { $command += ' --stage ' + $Stage }
if ($Mode -eq 'resume') { $command += ' --job ' + $Job }
if ($Mode -eq 'preflight') {
    $preflightOutput = & ssh.exe @options $target $command
    if ($LASTEXITCODE -ne 0) { throw ('Stock preflight stopped. No deployment started. Transport: ' + $remote) }
    $preflightOutput | ForEach-Object { Write-Host $_ }
    $results = @($preflightOutput | Where-Object { $_ -match '^\{"stage":' } | ForEach-Object { $_ | ConvertFrom-Json })
    if ($results.Count -ne 1 -or $results[0].stage -notmatch '^/opt/xiquan-releases/stock-stage-[0-9a-f]{32}$' -or
        $results[0].source_commit -cne $SourceCommit -or $results[0].source_sha256 -cne $ExpectedSha256) {
        throw 'Cloud preflight did not return one verified stage identity. Deployment not started.'
    }
    $results[0]
} else {
    & ssh.exe @options $target $command
    if ($LASTEXITCODE -ne 0) { throw ('Stock gate stopped. Retain printed PRIVATE_STOCK_JOB/evidence path. No automatic rollback or cleanup. Transport: ' + $remote) }
}
