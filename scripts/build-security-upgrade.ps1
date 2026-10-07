[CmdletBinding()]
param([switch]$SkipSignedMobile)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Invoke-CheckedScript {
    param([string]$Name, [string[]]$Arguments = @())
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot "scripts\$Name") @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Name failed. Release stopped; nothing was uploaded." }
}

Set-Location -LiteralPath $projectRoot
Invoke-CheckedScript 'test-all.ps1'
Invoke-CheckedScript 'publish-electron-update.ps1' @(
    '-ApiBaseUrl', 'https://api.pqxqxy.xyz/api', '-EcsTarget', 'root@39.96.217.210',
    '-MinimumVersion', '0.4.0', '-StageOnly'
)
if (-not $SkipSignedMobile) {
    Invoke-CheckedScript 'build-mobile-release.ps1' @(
        '-Version', '1.2.0', '-VersionCode', '7', '-MinimumVersionCode', '7',
        '-ReleaseNotes', '收银界面简化、资金接口加固与追责证据升级'
    )
    Invoke-CheckedScript 'publish-mobile-release.ps1' @('-Version', '1.2.0', '-StageOnly')
}
Invoke-CheckedScript 'build-web-release.ps1' @(
    '-BuildId', '20260930-security-040', '-ReleaseNotes', '收银快捷键、资金核对与审计证据升级'
)
Invoke-CheckedScript 'publish-web-release.ps1' @('-EcsTarget', 'root@39.96.217.210', '-StageOnly')
Invoke-CheckedScript 'build-mobile-web.ps1'
Invoke-CheckedScript 'build-cloud-bundle.ps1' @('-IncludeDesktopUpdate')
Write-Host 'Local release candidates are ready. No ECS files or database were changed.' -ForegroundColor Green
Write-Host (Join-Path $projectRoot 'client\release\Xiquan-Bathhouse-Setup-0.4.0.exe')
if (-not $SkipSignedMobile) { Write-Host (Join-Path $projectRoot 'release\mobile\xiquan-mobile-ordering-1.2.0.apk') }
Write-Host 'Follow docs\2026-09-30安全发布与事故追责.md before production deployment.'
