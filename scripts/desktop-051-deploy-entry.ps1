[CmdletBinding()]
param([ValidateSet('all','preflight','resume')][string]$Mode='all',[string]$EcsTarget='root@39.96.217.210',[string]$RecoveryIdentity)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$delivery=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
& node.exe (Join-Path $delivery.ProjectRoot 'scripts\lib\desktop-051.cjs') verify-delivery $PSScriptRoot
if($LASTEXITCODE-ne 0){throw 'Delivered bytes changed; no cloud operation.'}
$arguments=@{BundlePath=(Join-Path $PSScriptRoot $delivery.SourceZipFile);ExpectedSha256=$delivery.SourceSha256;SourceCommit=$delivery.SourceCommit;EcsTarget=$EcsTarget}
$entry=Join-Path $delivery.ProjectRoot 'scripts\invoke-desktop-051.ps1'
if($Mode-eq 'resume'){
    if(-not $RecoveryIdentity){throw 'Supply the exact LOCAL_RECOVERY_IDENTITY printed by the stopped operation.'}
    $identity=Get-Content -LiteralPath $RecoveryIdentity -Raw -Encoding UTF8|ConvertFrom-Json
    $result=& $entry @arguments -Mode resume -Stage $identity.Stage -JobDirectory $identity.Job
}else{
    $preflight=& $entry @arguments -Mode preflight
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot '云端预检结果.json'),($preflight|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
    if($Mode-eq 'preflight'){$preflight;return}
    $result=& $entry @arguments -Mode deploy -Stage $preflight.stage
}
if(-not $result.CloudChanged -or $result.SourceCommit-cne $delivery.SourceCommit){throw 'Exact completed result missing; do not publish.'}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot '云端部署结果.json'),($result|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
$result
