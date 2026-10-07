[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot,
    [string]$EcsTarget = 'root@39.96.217.210',
    [string]$RemoteCloudDir = '/opt/xiquan/xiquan/deploy/cloud',
    [switch]$StageOnly, [switch]$DryRun,
    [ValidateSet('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64')]
    [string[]]$Targets = @('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64'))
$ErrorActionPreference = 'Stop'
if ($EcsTarget -notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$') { throw 'SSH target is invalid.' }
$project = Split-Path -Parent $PSScriptRoot
$root = (Resolve-Path -LiteralPath $ReleaseRoot -ErrorAction Stop).Path
$stageParent = Join-Path $project 'release\windows-staging'
$stage = Join-Path $stageParent ('xiquan-windows-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
$policyPath = Join-Path $project 'deploy\cloud\releases\client-policy.json'
$nodeArgs = @((Join-Path $PSScriptRoot 'lib\windows-publish.cjs'), $root, $stage, $policyPath, $RemoteCloudDir)
$mode = 'live'; if ($DryRun) { $mode = 'dry' }
$nodeArgs += @($mode, ($Targets -join ','))
& node.exe @nodeArgs
if ($LASTEXITCODE -ne 0) { throw 'Release preflight failed; no SSH/SCP was run.' }
if ($DryRun) { Write-Host ('DryRun only: requested signatures verified (' + ($Targets -join ',') + '). No writes or uploads.'); return }
if (-not (Test-Path -LiteralPath (Join-Path $stage 'SHA256SUMS'))) { throw 'Staging incomplete; stopped.' }
if ($StageOnly) { Write-Host ('Verified local stage: ' + $stage); return }
$remoteStage = '/tmp/' + (Split-Path -Leaf $stage)
Write-Host 'Uploading verified installers; database/accounts are not modified.'
& scp.exe -r $stage ($EcsTarget + ':/tmp/')
if ($LASTEXITCODE -ne 0) { throw 'Upload failed. No channels were activated.' }
& ssh.exe $EcsTarget ('bash ' + $remoteStage + '/activate.sh')
if ($LASTEXITCODE -ne 0) { throw 'Activation stopped. Review which channels were activated; old files remain. Do not claim all targets succeeded.' }
& node.exe (Join-Path $PSScriptRoot 'lib\windows-public-check.cjs') $root ($Targets -join ',')
if ($LASTEXITCODE -ne 0) { throw 'Public content verification failed; inspect published channels before using automatic updates.' }
Write-Host ('Requested channels activated and publicly verified: ' + ($Targets -join ',') + '. Existing cloud data/mobile/web and unrequested policies preserved.')
