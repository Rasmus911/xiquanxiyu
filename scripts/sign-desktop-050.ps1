[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot,[string]$PrivateKeyPath='F:\溪泉洗浴系统\private\溪泉发布密钥\desktop-release-private.pem')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$release=(Resolve-Path -LiteralPath $ReleaseRoot).Path
$raw=& node.exe (Join-Path $PSScriptRoot 'lib\desktop-050.cjs') plan
if($LASTEXITCODE-ne 0){throw 'Original live signed policy unavailable. No sequence guessed, nothing signed.'}
$plan=($raw-join "`n")|ConvertFrom-Json
& node.exe (Join-Path $PSScriptRoot 'lib\desktop-050.cjs') verify-candidates $release
if($LASTEXITCODE-ne 0){throw 'Exact four candidates failed verification.'}
$notes=@('优化主登录页面','新增账号密码修改功能','新增搓澡师下单打印小票的功能','新增每天小票补打的功能')
foreach($row in $plan.previous){
    & (Join-Path $PSScriptRoot 'sign-windows-release.ps1') -ReleaseRoot $release -PrivateKeyPath $PrivateKeyPath `
        -Sequence $plan.sequence -MinimumVersion $row.minimum_version -Targets @($row.target) -ReleaseNotes $notes
}
Write-Host 'Original-trust channels signed locally. Nothing uploaded.'
