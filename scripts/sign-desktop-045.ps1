[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot,
    [Parameter(Mandatory)][string]$PrivateKeyPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath $ReleaseRoot).Path
# This verifies the live original-trust policies BEFORE asking for any secret.
$raw = & node.exe (Join-Path $PSScriptRoot 'lib\desktop-045.cjs')
if ($LASTEXITCODE -ne 0) { throw 'Live signed policy unavailable/invalid. No sequence guessed, no signing performed.' }
$plan = ($raw -join "`n") | ConvertFrom-Json
$targets = @($plan.previous | ForEach-Object { $_.target })
& node.exe (Join-Path $PSScriptRoot 'lib\desktop-045.cjs') verify-candidates $root
if ($LASTEXITCODE -ne 0) { throw 'Actual candidate verification failed.' }
foreach ($row in $plan.previous) {
    & (Join-Path $PSScriptRoot 'sign-windows-release.ps1') -ReleaseRoot $root -PrivateKeyPath $PrivateKeyPath `
        -Sequence $plan.sequence -MinimumVersion $row.minimum_version -Targets @($row.target) `
        -ReleaseNotes @('强制清空仅当前手牌并验证本人密码','会员及项目支持安全删除和编辑','岗位仅显示激活手牌；经营重置保留库存')
}
Write-Host 'Four original-trust update channels signed locally. Nothing uploaded; cloud/backend deployment must precede publication.'
