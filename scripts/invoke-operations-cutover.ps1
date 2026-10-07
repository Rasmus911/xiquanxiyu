[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$StageDirectory,
    [string]$EcsTarget='root@39.96.217.210',
    [ValidateSet('Prepare','Apply')][string]$Mode='Prepare',
    [string]$JobPath,
    [string]$PreviewSha256,
    [switch]$ApplyAfterPreview,
    [switch]$StageOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($StageDirectory -notmatch '^/opt/xiquan-releases/operations-stage-[0-9a-f]{32}$' -or $EcsTarget -ne 'root@39.96.217.210') {
    throw 'Only the verified existing ECS stage and target are allowed.'
}
if ($Mode -eq 'Apply' -and ($JobPath -notmatch '^/opt/xiquan-backups/operations-cutover-[0-9a-f]{32}$' -or $PreviewSha256 -notmatch '^[0-9a-f]{64}$')) {
    throw 'Apply requires the exact prepared recovery directory and preview SHA256.'
}
$project=Split-Path -Parent $PSScriptRoot
$tools=@('operations_deploy.py','operations_backup_verify.py','operations_preflight.py')
$records=@()
foreach ($name in $tools) {
    $path=(Resolve-Path -LiteralPath (Join-Path $project ('deploy\cloud\scripts\'+$name))).Path
    if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked deployment tool refused.' }
    $records+=@{Name=$name;Path=$path;Sha256=(Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant()}
}
if ($StageOnly) {
    [pscustomobject]@{StageOnly=$true;StageDirectory=$StageDirectory;Mode=$Mode;ToolCount=$records.Count;CloudChanged=$false}
    return
}
$remote='/tmp/xiquan-operations-cutover-tools-'+[guid]::NewGuid().ToString('N')
$options=@('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
& ssh.exe @options $EcsTarget ('umask 077 && mkdir -m 700 '+$remote)
if ($LASTEXITCODE -ne 0) { throw 'Private tool upload directory failed. No API change performed.' }
foreach ($record in $records) {
    & scp.exe @options -- $record.Path ($EcsTarget+':'+$remote+'/'+$record.Name)
    if ($LASTEXITCODE -ne 0) { throw 'Reviewed tool upload failed. No cutover attempted.' }
}
$hashes=& ssh.exe @options $EcsTarget ('sha256sum '+(($records | ForEach-Object {$remote+'/'+$_.Name}) -join ' '))
if ($LASTEXITCODE -ne 0) { throw 'Remote tool hash query failed. No cutover attempted.' }
foreach ($record in $records) {
    $pattern='^'+[regex]::Escape($record.Sha256)+'\s+\*?'+[regex]::Escape($remote+'/'+$record.Name)+'$'
    if (@($hashes | Where-Object {$_ -match $pattern}).Count -ne 1) { throw 'Uploaded tool hash mismatch. Do not deploy.' }
}
$driver='python3 '+$remote+'/operations_deploy.py'
function Invoke-ReviewedStep([string]$Command) {
    $lines=New-Object 'System.Collections.Generic.List[string]'
    & ssh.exe @options $EcsTarget $Command | ForEach-Object {
        Write-Host $_
        [void]$lines.Add([string]$_)
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cloud step stopped. Retain the printed private recovery directory; send the last phase/error. Do not run old update/restore scripts.' }
    return $lines.ToArray()
}
if ($Mode -eq 'Prepare') {
    Write-Host 'Preparing maintenance. API writes stop during backup, restore and migration. No accounts or financial data are cleared.'
    $output=@(Invoke-ReviewedStep ($driver+' --mode prepare --stage '+$StageDirectory))
    $marker=@($output | Where-Object {$_ -like 'DEPLOY_PREVIEW_READY_JSON=*'})
    if ($marker.Count -ne 1) { throw 'No valid prepared preview received. Do not apply.' }
    $prepared=$marker[0].Substring('DEPLOY_PREVIEW_READY_JSON='.Length) | ConvertFrom-Json
    if ($prepared.status -ne 'preview_ready' -or $prepared.job_path -notmatch '^/opt/xiquan-backups/operations-cutover-[0-9a-f]{32}$' -or $prepared.preview_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'Prepared recovery/preview identity is invalid. Do not apply.'
    }
    $JobPath=$prepared.job_path
    $PreviewSha256=$prepared.preview_sha256
    if (-not $ApplyAfterPreview) {
        Write-Host ('PREPARED_JOB='+$JobPath)
        Write-Host ('PREVIEW_SHA256='+$PreviewSha256)
        Write-Host 'API is stopped. Business replacement is not yet performed. Keep this output for explicit Apply.'
        return
    }
    Write-Host 'Verified preview: 100 wristbands (male 001-050, female 051-100), 42 formal entries. Existing products/stock, member balances, accounts and historical evidence are retained.'
    Write-Host ('Private recovery directory: '+$JobPath)
    Write-Host ('Preview SHA256: '+$PreviewSha256)
    $suffix=$PreviewSha256.Substring(56,8)
    $answer=Read-Host ('To apply this preview and restart the new API, type the last 8 SHA256 characters ('+$suffix+')')
    if ($answer -cne $suffix) { throw 'Preview not confirmed. API remains stopped and all backups are retained. Use explicit Apply with the printed job/SHA later.' }
}
[void](Invoke-ReviewedStep ($driver+' --mode apply --stage '+$StageDirectory+' --job '+$JobPath+' --preview-sha256 '+$PreviewSha256))
