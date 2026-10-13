[CmdletBinding()]
param([ValidateSet('all','sign','publish','verify')][string]$Mode='all',[string]$EcsTarget='root@39.96.217.210',[string]$PrivateKeyPath)
$ErrorActionPreference='Stop'
$info=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
& (Join-Path $info.ProjectRoot 'scripts\publish-desktop-054.ps1') -DeliveryRoot $PSScriptRoot -Mode $Mode -EcsTarget $EcsTarget -PrivateKeyPath $PrivateKeyPath
