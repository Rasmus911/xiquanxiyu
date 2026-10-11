[CmdletBinding()]
param(
    [ValidateSet('build','publish','all','validate')][string]$Mode = 'all',
    [string]$EcsTarget = 'root@39.96.217.210',
    [string]$PreviousApkPath = 'F:\溪泉洗浴系统\release\mobile\xiquan-mobile-ordering-1.2.7.apk'
)
$ErrorActionPreference = 'Stop'
$info = Join-Path $PSScriptRoot '交付信息.json'
$modes = if ($Mode -eq 'all') { @('build','publish') } else { @($Mode) }
foreach ($step in $modes) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\mobile-128-entry.ps1' `
        -Mode $step -DeliveryInfoPath $info -EcsTarget $EcsTarget -PreviousApkPath $PreviousApkPath
    if ($LASTEXITCODE -ne 0) { throw ('已停止于：' + $step + '。请保留完整输出；不要卸载旧 APP 或更换证书。') }
}
