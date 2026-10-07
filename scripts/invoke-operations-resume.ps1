[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$StageDirectory,
    [Parameter(Mandatory=$true)][string]$JobDirectory,
    [Parameter(Mandatory=$true)][string]$ImageReceipt,
    [string]$EcsTarget='root@39.96.217.210',
    [ValidateSet('OfflineImage','Preview')][string]$Checkpoint='OfflineImage',
    [switch]$ApplyAfterPreview,
    [switch]$StageOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($StageDirectory -notmatch '^/opt/xiquan-releases/operations-stage-[0-9a-f]{32}$' -or
    $JobDirectory -notmatch '^/opt/xiquan-backups/operations-cutover-[0-9a-f]{32}$' -or
    $ImageReceipt -notmatch ('^'+[regex]::Escape($JobDirectory)+'/offline-image-[0-9a-f]{32}/verified-image\.json$') -or
    $EcsTarget -ne 'root@39.96.217.210') {
    throw 'Only the existing verified ECS source, recovery job and image receipt are allowed.'
}
$project=Split-Path -Parent $PSScriptRoot
$names=@('operations_deploy.py','operations_backup_verify.py','operations_preflight.py','operations_offline_build.py','operations_resume.py')
if ($Checkpoint -eq 'Preview') { $names+=@('operations_preview_recovery.py') }
$records=@()
foreach ($name in $names) {
    $path=(Resolve-Path -LiteralPath (Join-Path $project ('deploy\cloud\scripts\'+$name))).Path
    if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked tool refused.' }
    $records+=@{Name=$name;Path=$path;Sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
}
if ($StageOnly) {
    [pscustomobject]@{StageOnly=$true;ToolCount=$records.Count;CloudChanged=$false;Rebuild=$false;DatabaseClearing=$false}
    return
}
$remote='/tmp/xiquan-operations-resume-tools-'+[guid]::NewGuid().ToString('N')
$options=@('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
& ssh.exe @options $EcsTarget ('umask 077 && mkdir -m 700 '+$remote)
if ($LASTEXITCODE -ne 0) { throw 'Private tool directory failed; resume not attempted.' }
foreach ($record in $records) {
    & scp.exe @options -- $record.Path ($EcsTarget+':'+$remote+'/'+$record.Name)
    if ($LASTEXITCODE -ne 0) { throw 'Tool upload failed; resume not attempted.' }
}
$hashes=& ssh.exe @options $EcsTarget ('sha256sum '+(($records | ForEach-Object {$remote+'/'+$_.Name}) -join ' '))
if ($LASTEXITCODE -ne 0) { throw 'Tool hash query failed; resume not attempted.' }
foreach ($record in $records) {
    $pattern='^'+[regex]::Escape($record.Sha256)+'\s+\*?'+[regex]::Escape($remote+'/'+$record.Name)+'$'
    if (@($hashes | Where-Object {$_ -match $pattern}).Count -ne 1) { throw 'Uploaded tool hash mismatch; stopped.' }
}
function Invoke-ResumeStep([string]$Command) {
    $lines=New-Object 'System.Collections.Generic.List[string]'
    & ssh.exe @options $EcsTarget $Command | ForEach-Object {
        Write-Host $_
        [void]$lines.Add([string]$_)
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cloud step stopped. Retain this recovery directory and last phase. Do not repeat Prepare or restore blindly.' }
    return $lines.ToArray()
}
Write-Host ('Resuming checkpoint: '+$Checkpoint+'. No rebuild, account clearing, installer publication or cleanup.')
Write-Host ('Recovery directory: '+$JobDirectory)
$prepareCommand='python3 -B '+$remote+'/operations_resume.py --stage '+$StageDirectory+' --job '+$JobDirectory+' --image-receipt '+$ImageReceipt
if ($Checkpoint -eq 'Preview') {
    $prepareCommand='python3 -B '+$remote+'/operations_preview_recovery.py --mode prepare --stage '+$StageDirectory+' --job '+$JobDirectory+' --image-receipt '+$ImageReceipt
    Write-Host 'Migration and restore are already verified. Only private preview and remaining cutover will run.'
}
$output=@(Invoke-ResumeStep $prepareCommand)
$markers=@($output | Where-Object {$_ -like 'DEPLOY_PREVIEW_READY_JSON=*'})
if ($markers.Count -ne 1) { throw 'No prepared preview received; do not apply.' }
$prepared=$markers[0].Substring('DEPLOY_PREVIEW_READY_JSON='.Length) | ConvertFrom-Json
if ($prepared.status -ne 'preview_ready' -or $prepared.job_path -cne $JobDirectory -or
    $prepared.stage -cne $StageDirectory -or $prepared.preview_sha256 -notmatch '^[0-9a-f]{64}$' -or
    $prepared.active_wristbands -ne 100 -or $prepared.formal_items -ne 42 -or
    $prepared.retained_money_and_history -ne $true) { throw 'Prepared preview identity or retention checks invalid.' }
$previewSha=$prepared.preview_sha256
Write-Host ('PREPARED_JOB='+$JobDirectory)
Write-Host ('PREVIEW_SHA256='+$previewSha)
if (-not $ApplyAfterPreview) {
    Write-Host 'API remains stopped. Preview ready; business replacement has not been applied.'
    return
}
Write-Host 'Preview: male 001-050, female 051-100; 42 formal entries. Existing products/stock, accounts, balances and history retained.'
$suffix=$previewSha.Substring(56,8)
$answer=Read-Host ('To apply and restart the new API, type the last 8 SHA256 characters ('+$suffix+')')
if ($answer -cne $suffix) { throw 'Preview not confirmed. Keep PREPARED_JOB and PREVIEW_SHA256 for explicit Apply; API remains stopped.' }
$applyCommand='python3 -B '+$remote+'/operations_deploy.py --mode apply --stage '+$StageDirectory+' --job '+$JobDirectory+' --preview-sha256 '+$previewSha
if ($Checkpoint -eq 'Preview') {
    $applyCommand='python3 -B '+$remote+'/operations_preview_recovery.py --mode apply --stage '+$StageDirectory+' --job '+$JobDirectory+' --image-receipt '+$ImageReceipt+' --preview-sha256 '+$previewSha
}
$result=@(Invoke-ResumeStep $applyCommand)
if (@($result | Where-Object {$_ -ceq 'OPERATIONS_CLOUD_DEPLOYED_OK'}).Count -ne 1) {
    throw 'No verified cloud deployment completion marker. Retain all evidence.'
}
Write-Host 'Cloud API/web cutover verified. Existing update feeds/installers and all backups retained.'
