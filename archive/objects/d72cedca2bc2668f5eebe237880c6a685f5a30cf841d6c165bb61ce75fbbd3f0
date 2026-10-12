[CmdletBinding()]
param([string]$EcsTarget='root@39.96.217.210',[string]$PrivateKeyPath)
$ErrorActionPreference='Stop'
$delivery=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $PrivateKeyPath){$PrivateKeyPath=Join-Path $delivery.ProjectRoot 'private\溪泉发布密钥\desktop-release-private.pem'}
& node.exe (Join-Path $delivery.ProjectRoot 'scripts\lib\reviewed-source.cjs') $delivery.ProjectRoot $delivery.SourceCommit
if($LASTEXITCODE-ne 0){throw 'Frozen source differs; no signing/publication.'}
& (Join-Path $PSScriptRoot '03-验证三端与更新.ps1') -EcsTarget $EcsTarget | Out-Host
if((Read-Host 'Exact cloud completed verified. Type PUBLISH 0.5.1')-cne 'PUBLISH 0.5.1'){throw 'Publication cancelled.'}
& (Join-Path $delivery.ProjectRoot 'scripts\sign-desktop-051.ps1') -ReleaseRoot $delivery.ReleaseRoot -PrivateKeyPath $PrivateKeyPath
& (Join-Path $delivery.ProjectRoot 'scripts\publish-windows-release.ps1') -ReleaseRoot $delivery.ReleaseRoot -EcsTarget $EcsTarget -Targets $delivery.Targets
Write-Host 'Four signed update channels published and verified; existing mobile APK retained.'
