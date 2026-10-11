[CmdletBinding()]
param([string]$EcsTarget = 'root@39.96.217.210')
$ErrorActionPreference = 'Stop'
$info = Join-Path $PSScriptRoot '交付信息.json'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\mobile-128-entry.ps1' `
    -Mode api -DeliveryInfoPath $info -EcsTarget $EcsTarget
if ($LASTEXITCODE -ne 0) { throw '云端补丁未完成，请保留完整输出，不要继续发布或重跑旧部署脚本。' }
