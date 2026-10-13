[CmdletBinding()]
param([string]$OutputDirectory,[switch]$DryRun)
$ErrorActionPreference='Stop'
$project=Split-Path -Parent $PSScriptRoot
if(-not $OutputDirectory){$OutputDirectory=Join-Path $project '最新版安装包-刷卡开牌-0.5.4'}
if(Test-Path -LiteralPath $OutputDirectory){throw 'Delivery exists. Retain it; use a new OutputDirectory for a new build.'}
$public=Join-Path $project 'release\trust\release-public-key.pem'
$cache=Join-Path $project 'release\runtime-cache\current-windows'
$contractText=& node.exe (Join-Path $PSScriptRoot 'lib\desktop-054-source.cjs') inspect $project
if($LASTEXITCODE-ne 0){throw 'Source contract failed. No build or upload.'}
$contract=($contractText-join "`n")|ConvertFrom-Json
$commit=$contract.source_commit
$buildId='desktop054-'+$commit.Substring(0,12)+'-'+(Get-Date -Format 'yyyyMMddHHmmss')
$targets=@('win10-x86','win10-x64','win11-x86','win11-x64')
& (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.5.4' -BuildId $buildId -Targets $targets -PublicKeyPath $public -OfflineRuntimeCache $cache -DryRun
if($DryRun){Write-Host 'LOCAL_PREFLIGHT_ONLY: no files signed, built or uploaded.';return}
$oldApi=$env:VITE_API_BASE_URL;$oldBuild=$env:VITE_BUILD_ID
try{
    $env:VITE_API_BASE_URL='https://api.pqxqxy.xyz/api';$env:VITE_BUILD_ID=$commit
    foreach($area in @('client','mobile')){
        Push-Location -LiteralPath (Join-Path $project $area)
        try{& npm.cmd run build;if($LASTEXITCODE-ne 0){throw ('Frontend failed: '+$area)}}finally{Pop-Location}
    }
    $version=[ordered]@{buildId=$commit;required=$false;releaseNotes=@('用ID卡读取手牌号来实现开牌的效果');publicationState='pending'}
    [IO.File]::WriteAllText((Join-Path $project 'client\dist\version.json'),($version|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    $source=& (Join-Path $PSScriptRoot 'build-desktop-054-source.ps1') -SourceRoot $project -AssetSourceCommit $commit
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.5.4' -BuildId $buildId -Targets $targets -PublicKeyPath $public -OfflineRuntimeCache $cache -SkipRenderer
    & node.exe (Join-Path $PSScriptRoot 'lib\reviewed-source.cjs') $project $commit
    if($LASTEXITCODE-ne 0){throw 'Source changed during build; preserve artifacts, no delivery.'}
    $release=Join-Path $project ('release\windows\0.5.4\'+$buildId)
    $state=& node.exe (Join-Path $PSScriptRoot 'lib\desktop-054.cjs') status $release
    if($LASTEXITCODE-ne 0){throw 'Actual installer identity verification failed.'}
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
    foreach($target in $targets){Copy-Item -LiteralPath (Join-Path $release ($target+'\Xiquan-Bathhouse-Setup-0.5.4-'+$target+'.exe')) -Destination $OutputDirectory}
    Copy-Item -LiteralPath $public -Destination $OutputDirectory
    Copy-Item -LiteralPath $source.ZipPath -Destination $OutputDirectory
    $entries=@{'desktop-054-cloud-entry.ps1'='01-部署云端.ps1';'desktop-054-windows-entry.ps1'='02-签名并发布桌面更新.ps1';'desktop-054-mobile-entry.ps1'='03-构建并发布安卓更新.ps1'}
    foreach($entry in $entries.Keys){Copy-Item -LiteralPath (Join-Path $PSScriptRoot $entry) -Destination (Join-Path $OutputDirectory $entries[$entry])}
    Copy-Item -LiteralPath (Join-Path $project 'docs\releases\desktop-0.5.4.md') -Destination (Join-Path $OutputDirectory 'README-完整PowerShell.md')
    $history=& node.exe (Join-Path $PSScriptRoot 'lib\desktop-054.cjs') retained-history $project
    if($LASTEXITCODE-ne 0){throw 'Historical original signatures could not be verified.'}
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'historical-signed-releases.json'),($history-join "`n"),[Text.UTF8Encoding]::new($false))
    $metadata=@{Version='0.5.4';BuildId=$buildId;ProjectRoot=$project;ReleaseRoot=$release;Targets=$targets;SourceCommit=$commit;
        SourceZipFile=(Split-Path -Leaf $source.ZipPath);SourceSha256=$source.Sha256;MobileVersion='1.2.11';MobileVersionCode=18;
        MinimumVersionCode=9;ApiChanged=$true;DatabaseChanged=$true;Status=@{Windows='candidate-built; original signature pending';Android='user hidden original-certificate build pending';Cloud='not contacted';ActualDevices='not tested';Archive='pending remote proof'}}
    $infoPath=Join-Path $OutputDirectory '交付信息.json'
    $metadata|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $infoPath -Encoding UTF8
    & node.exe (Join-Path $PSScriptRoot 'lib\desktop-054-source.cjs') delivery $OutputDirectory
    if($LASTEXITCODE-ne 0){throw 'Delivery manifest generation or verification failed.'}
    Write-Host ('LOCAL_CANDIDATES_READY='+$OutputDirectory)
    Write-Host 'No signing, ECS connection, deployment or old-version deletion performed.'
}finally{$env:VITE_API_BASE_URL=$oldApi;$env:VITE_BUILD_ID=$oldBuild}
