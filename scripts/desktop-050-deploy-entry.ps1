[CmdletBinding()]
param([ValidateSet('all','preflight','deploy','resume')][string]$Mode='all',[string]$Stage,[string]$Job,[string]$EcsTarget='root@39.96.217.210',[switch]$StageOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$delivery=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$bundle=Join-Path $PSScriptRoot $delivery.SourceZipFile
if((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()-cne $delivery.SourceSha256){throw 'SOURCE hash mismatch; stopped before connection.'}
$arguments=@{Mode=$Mode;BundlePath=$bundle;ExpectedSha256=$delivery.SourceSha256;SourceCommit=$delivery.SourceCommit;EcsTarget=$EcsTarget}
if($Stage){$arguments.Stage=$Stage};if($Job){$arguments.Job=$Job};if($StageOnly){$arguments.StageOnly=$true}
$result=& (Join-Path $delivery.ProjectRoot 'scripts\invoke-desktop-050.ps1') @arguments
if($result -and $result.PSObject.Properties.Name-contains 'CloudChanged' -and $result.CloudChanged){
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot '云端部署结果.json'),($result|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($true))
}
$result
