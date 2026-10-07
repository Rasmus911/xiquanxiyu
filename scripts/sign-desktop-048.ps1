[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot,
    [Parameter(Mandatory)][string]$PrivateKeyPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath $ReleaseRoot).Path
# This verifies the live original-trust policies BEFORE asking for any secret.
$raw = & node.exe (Join-Path $PSScriptRoot 'lib\desktop-045.cjs') plan '0.4.8'
if ($LASTEXITCODE -ne 0) { throw 'Live signed policy unavailable/invalid. No sequence guessed, no signing performed.' }
$plan = ($raw -join "`n") | ConvertFrom-Json
$targets = @($plan.previous | ForEach-Object { $_.target })
& node.exe (Join-Path $PSScriptRoot 'lib\desktop-045.cjs') verify-candidates $root '0.4.8'
if ($LASTEXITCODE -ne 0) { throw 'Actual candidate verification failed.' }
foreach ($row in $plan.previous) {
    & (Join-Path $PSScriptRoot 'sign-windows-release.ps1') -ReleaseRoot $root -PrivateKeyPath $PrivateKeyPath `
        -Sequence $plan.sequence -MinimumVersion $row.minimum_version -Targets @($row.target) `
        -ReleaseNotes @('1. 澡巾、备品、搓泥宝改为服务项目','2. 加单后弹窗选择耗材','3. 库存和项目商品每页10项，右上角翻页','4. 库存显示和编辑成本单价，已设置成本修改需本人密码')
}
Write-Host 'Four original-trust update channels signed locally. Nothing uploaded; cloud/backend deployment must precede publication.'
