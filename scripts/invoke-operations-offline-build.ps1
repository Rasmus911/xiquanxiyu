[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$StageDirectory,
    [Parameter(Mandatory=$true)][string]$JobDirectory,
    [string]$EcsTarget='root@39.96.217.210',
    [switch]$StageOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($StageDirectory -notmatch '^/opt/xiquan-releases/operations-stage-[0-9a-f]{32}$' -or
    $JobDirectory -notmatch '^/opt/xiquan-backups/operations-cutover-[0-9a-f]{32}$' -or
    $EcsTarget -ne 'root@39.96.217.210') {
    throw 'Only the verified existing ECS stage and recovery job are permitted.'
}
$project=Split-Path -Parent $PSScriptRoot
$names=@('operations_deploy.py','operations_backup_verify.py','operations_preflight.py','operations_offline_build.py')
$records=@()
foreach ($name in $names) {
    $path=(Resolve-Path -LiteralPath (Join-Path $project ('deploy\cloud\scripts\'+$name))).Path
    if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Linked maintenance tool refused.'
    }
    $records+=@{Name=$name;Path=$path;Sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
}
if ($StageOnly) {
    [pscustomobject]@{StageOnly=$true;ToolCount=$records.Count;CloudChanged=$false;ImageBuildPerformed=$false}
    return
}
$remote='/tmp/xiquan-offline-image-tools-'+[guid]::NewGuid().ToString('N')
$options=@('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
& ssh.exe @options $EcsTarget ('umask 077 && mkdir -m 700 '+$remote)
if ($LASTEXITCODE -ne 0) { throw 'Private tool directory creation failed. No takeover attempted.' }
foreach ($record in $records) {
    & scp.exe @options -- $record.Path ($EcsTarget+':'+$remote+'/'+$record.Name)
    if ($LASTEXITCODE -ne 0) { throw 'Maintenance tool upload failed. No takeover attempted.' }
}
$hashes=& ssh.exe @options $EcsTarget ('sha256sum '+(($records | ForEach-Object {$remote+'/'+$_.Name}) -join ' '))
if ($LASTEXITCODE -ne 0) { throw 'Uploaded tool hash query failed. No takeover attempted.' }
foreach ($record in $records) {
    $pattern='^'+[regex]::Escape($record.Sha256)+'\s+\*?'+[regex]::Escape($remote+'/'+$record.Name)+'$'
    if (@($hashes | Where-Object {$_ -match $pattern}).Count -ne 1) {
        throw 'Uploaded maintenance tool hash mismatch. No takeover attempted.'
    }
}
Write-Host 'Checking original dependencies, backup and schema before signalling the matched stalled build.'
Write-Host 'Image build only. No API start, migration, database clearing, publication or cleanup.'
& ssh.exe @options $EcsTarget ('python3 -B '+$remote+'/operations_offline_build.py --stage '+$StageDirectory+' --job '+$JobDirectory)
if ($LASTEXITCODE -ne 0) {
    throw 'Offline image recovery stopped. Keep the recovery directory and last output; do not restart or restore blindly.'
}
