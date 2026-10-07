[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot,
    [Parameter(Mandatory)][string]$PrivateKeyPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath $ReleaseRoot).Path
# This verifies the live original-trust policies BEFORE asking for any secret.
$raw = & node.exe (Join-Path $PSScriptRoot 'lib\desktop-045.cjs') plan '0.4.7'
if ($LASTEXITCODE -ne 0) { throw 'Live signed policy unavailable/invalid. No sequence guessed, no signing performed.' }
$plan = ($raw -join "`n") | ConvertFrom-Json
$targets = @($plan.previous | ForEach-Object { $_.target })
& node.exe (Join-Path $PSScriptRoot 'lib\desktop-045.cjs') verify-candidates $root '0.4.7'
if ($LASTEXITCODE -ne 0) { throw 'Actual candidate verification failed.' }
foreach ($row in $plan.previous) {
    & (Join-Path $PSScriptRoot 'sign-windows-release.ps1') -ReleaseRoot $root -PrivateKeyPath $PrivateKeyPath `
        -Sequence $plan.sequence -MinimumVersion $row.minimum_version -Targets @($row.target) `
        -ReleaseNotes @('1. 给前台收银和库管增补“经营报表”权限','2. “经营报表”UI优化','3. “库存管理”界面 UI优化','4. 库存预警值设置为商品入库数量的15%')
}
Write-Host 'Four original-trust update channels signed locally. Nothing uploaded; cloud/backend deployment must precede publication.'
