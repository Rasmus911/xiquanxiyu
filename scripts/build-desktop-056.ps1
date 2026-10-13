[CmdletBinding()]
param([string]$OutputDirectory,[switch]$DryRun)
$ErrorActionPreference='Stop'
$project=Split-Path -Parent $PSScriptRoot
if(-not $OutputDirectory){$OutputDirectory=Join-Path $project '最新版安装包-溪泉图标与库存布局-0.5.6'}
if(Test-Path -LiteralPath $OutputDirectory){throw 'Keep existing delivery; use a new OutputDirectory if rebuilding.'}
$contractText=& node.exe (Join-Path $PSScriptRoot 'lib\desktop-056-source.cjs') inspect $project
if($LASTEXITCODE-ne 0){throw 'Committed source contract failed.'}
$commit=($contractText|ConvertFrom-Json).source_commit
$buildId='desktop056-'+$commit.Substring(0,12)+'-'+(Get-Date -Format 'yyyyMMddHHmmss')
$public=Join-Path $project 'release\trust\release-public-key.pem'
$cache=Join-Path $project 'release\runtime-cache\current-windows'
$targets=@('win10-x86','win10-x64','win11-x86','win11-x64')
& (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.5.6' -BuildId $buildId -Targets $targets -PublicKeyPath $public -OfflineRuntimeCache $cache -DryRun
if($DryRun){Write-Host 'LOCAL_PREFLIGHT_ONLY; no build/signing/connection.';return}
$oldApi=$env:VITE_API_BASE_URL;$oldBuild=$env:VITE_BUILD_ID
try{
 $env:VITE_API_BASE_URL='https://api.pqxqxy.xyz/api';$env:VITE_BUILD_ID=$commit
 foreach($area in @('client','mobile')){
  Push-Location -LiteralPath (Join-Path $project $area)
  try{& npm.cmd run build;if($LASTEXITCODE-ne 0){throw ('Frontend failed: '+$area)}}finally{Pop-Location}
 }
 $version=@{buildId=$commit;required=$false;releaseNotes=@('给桌面端的图标做出更换','优化“库存”页面布局');publicationState='pending'}
 [IO.File]::WriteAllText((Join-Path $project 'client\dist\version.json'),($version|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
 $source=& (Join-Path $PSScriptRoot 'build-desktop-056-source.ps1') -SourceRoot $project -AssetSourceCommit $commit
 & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.5.6' -BuildId $buildId -Targets $targets -PublicKeyPath $public -OfflineRuntimeCache $cache -SkipRenderer
 $release=Join-Path $project ('release\windows\0.5.6\'+$buildId)
 & node.exe (Join-Path $PSScriptRoot 'lib\desktop-056.cjs') status $release
 if($LASTEXITCODE-ne 0){throw 'Installer identity failed; no delivery.'}
 New-Item -ItemType Directory -Path $OutputDirectory|Out-Null
 foreach($target in $targets){Copy-Item -LiteralPath (Join-Path $release ($target+'\Xiquan-Bathhouse-Setup-0.5.6-'+$target+'.exe')) -Destination $OutputDirectory}
 Copy-Item -LiteralPath $public,$source.ZipPath,(Join-Path $project 'server\app\inventory_xlsx.py') -Destination $OutputDirectory
 Copy-Item -LiteralPath (Join-Path $project 'client\electron\assets\xiquan.png') -Destination (Join-Path $OutputDirectory '图标预览.png')
 $dist=Join-Path $project 'client\dist'
 Compress-Archive -LiteralPath (Join-Path $dist 'assets'),(Join-Path $dist 'index.html'),(Join-Path $dist 'version.json') -DestinationPath (Join-Path $OutputDirectory 'web-0.5.6.zip')
 $entries=@{
  '01-部署云端.ps1'=@'
[CmdletBinding()]
param([string]$EcsTarget='root@39.96.217.210',[switch]$ValidateOnly,[switch]$VerifyOnly)
$ErrorActionPreference='Stop'
$info=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
& (Join-Path $info.ProjectRoot 'scripts\publish-cloud-056.ps1') -DeliveryRoot $PSScriptRoot -EcsTarget $EcsTarget -ValidateOnly:$ValidateOnly -VerifyOnly:$VerifyOnly
'@
  '02-签名并发布桌面更新.ps1'=@'
[CmdletBinding()]
param([ValidateSet('all','sign','publish','verify')][string]$Mode='all',[string]$EcsTarget='root@39.96.217.210',[switch]$PreflightOnly)
$ErrorActionPreference='Stop'
$info=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
& (Join-Path $info.ProjectRoot 'scripts\publish-desktop-056.ps1') -DeliveryRoot $PSScriptRoot -Mode $Mode -EcsTarget $EcsTarget -PreflightOnly:$PreflightOnly
'@
  '03-构建并发布安卓更新.ps1'=@'
[CmdletBinding()]
param([ValidateSet('all','build','publish','validate')][string]$Mode='all',[string]$EcsTarget='root@39.96.217.210',[string]$PreviousApkPath)
$ErrorActionPreference='Stop'
$info=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
& (Join-Path $info.ProjectRoot 'scripts\publish-mobile-1213.ps1') -DeliveryRoot $PSScriptRoot -Mode $Mode -EcsTarget $EcsTarget -PreviousApkPath $PreviousApkPath
'@
  '完整发布指令.ps1'=@'
[CmdletBinding()]
param([ValidateSet('all','cloud','windows','android','verify')][string]$Mode='all',[string]$EcsTarget='root@39.96.217.210')
$ErrorActionPreference='Stop'
$info=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
& node.exe (Join-Path $info.ProjectRoot 'scripts\lib\desktop-056.cjs') verify-delivery $PSScriptRoot
if($LASTEXITCODE-ne 0){throw 'Delivery check failed; nothing uploaded.'}
if($Mode-eq 'verify'){return}
$steps=switch($Mode){'all'{@('01-部署云端.ps1','02-签名并发布桌面更新.ps1','03-构建并发布安卓更新.ps1')};'cloud'{@('01-部署云端.ps1')};'windows'{@('02-签名并发布桌面更新.ps1')};'android'{@('03-构建并发布安卓更新.ps1')}}
foreach($name in $steps){
 Write-Host ('正在执行：'+$name)
 & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot $name) -EcsTarget $EcsTarget
 if($LASTEXITCODE-ne 0){throw ($name+' 未完成。保留证据，只处理失败步骤，不重跑全部发布。')}
}
'@
 }
 foreach($name in $entries.Keys){[IO.File]::WriteAllText((Join-Path $OutputDirectory $name),$entries[$name],[Text.UTF8Encoding]::new($true))}
 Copy-Item -LiteralPath (Join-Path $project 'docs\releases\desktop-0.5.6.md') -Destination (Join-Path $OutputDirectory 'README-完整PowerShell.md')
 $history=& node.exe (Join-Path $PSScriptRoot 'lib\desktop-056.cjs') retained-history $project
 if($LASTEXITCODE-ne 0){throw 'Original signed history verification failed'}
 [IO.File]::WriteAllText((Join-Path $OutputDirectory 'historical-signed-releases.json'),($history-join "`n"),[Text.UTF8Encoding]::new($false))
 $webRecords=& node.exe (Join-Path $PSScriptRoot 'lib\static-056-public.cjs') manifest $dist
 if($LASTEXITCODE-ne 0){throw 'Web manifest failed'}
 $metadata=@{Version='0.5.6';BuildId=$buildId;ProjectRoot=$project;ReleaseRoot=$release;Targets=$targets;SourceCommit=$commit;SourceZipFile=(Split-Path -Leaf $source.ZipPath);SourceSha256=$source.Sha256;WebSha256=(Get-FileHash -LiteralPath (Join-Path $OutputDirectory 'web-0.5.6.zip')).Hash.ToLowerInvariant();ApiSha256=(Get-FileHash -LiteralPath (Join-Path $OutputDirectory 'inventory_xlsx.py')).Hash.ToLowerInvariant();WebFiles=($webRecords|ConvertFrom-Json);MobileVersion='1.2.13';MobileVersionCode=20;MinimumVersionCode=9;ApiChanged=$true;DatabaseChanged=$false}
 [IO.File]::WriteAllText((Join-Path $OutputDirectory '交付信息.json'),($metadata|ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
 & node.exe (Join-Path $PSScriptRoot 'lib\desktop-056-source.cjs') delivery $OutputDirectory
 if($LASTEXITCODE-ne 0){throw 'Delivery manifest validation failed'}
 Write-Host ('LOCAL056_CANDIDATES_READY='+$OutputDirectory)
 Write-Host 'Original update-policy signing and Android certificate input remain user-run. Cloud was not contacted.'
}finally{$env:VITE_API_BASE_URL=$oldApi;$env:VITE_BUILD_ID=$oldBuild}
