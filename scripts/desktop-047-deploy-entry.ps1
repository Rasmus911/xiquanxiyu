[CmdletBinding()]
param([ValidateSet('all','preflight','deploy','resume')][string]$Mode='all',[string]$Stage,[string]$Job)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$delivery=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$bundle=Join-Path $PSScriptRoot $delivery.SourceZipFile
if((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()-cne $delivery.SourceSha256){throw 'SOURCE archive hash mismatch. Stopped before connection.'}
$arguments=@{Mode=$Mode;BundlePath=$bundle;ExpectedSha256=$delivery.SourceSha256;SourceCommit=$delivery.SourceCommit}
if($Stage){$arguments.Stage=$Stage}; if($Job){$arguments.Job=$Job}
& (Join-Path $delivery.ProjectRoot 'scripts\invoke-desktop-047.ps1') @arguments
