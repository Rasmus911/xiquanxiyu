[CmdletBinding()]
param([string]$OutputDirectory,[switch]$DryRun)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path -Parent $PSScriptRoot
if(-not $OutputDirectory){$OutputDirectory=Join-Path $root '最新版安装包-实体卡消费-0.5.1'}
$public=Join-Path $root 'release\trust\release-public-key.pem'
$cache=Join-Path $root 'release\runtime-cache\current-windows'
$targets=@('win10-x86','win10-x64','win11-x86','win11-x64')
$check=@'
const path=require('node:path'),root=process.argv[1];
const actual=require(path.join(root,'client/build/windows-pack.cjs')).publicTrust(process.argv[2]);
const trust=require(path.join(root,'scripts/lib/desktop-051.cjs')).trust;
if(actual.keyId!==trust.keyId||actual.publicKeyPem!==trust.publicKeyPem)throw Error('Original public key required');
'@
& node.exe -e $check $root $public
if($LASTEXITCODE-ne 0){throw 'Original trust check failed.'}
$contractRaw=& node.exe (Join-Path $PSScriptRoot 'lib\desktop-051.cjs') inspect $root
if($LASTEXITCODE-ne 0){throw 'Committed source contract failed.'}
$contract=($contractRaw-join "`n")|ConvertFrom-Json
$commit=$contract.source_commit
$buildId='desktop051-'+$commit.Substring(0,12)+'-'+(Get-Date -Format 'yyyyMMddHHmmss')
& (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.5.1' -BuildId $buildId -Targets $targets -PublicKeyPath $public -OfflineRuntimeCache $cache -DryRun
if($DryRun){Write-Host 'Preflight only; no packages or upload.';return}
if(Test-Path -LiteralPath $OutputDirectory){throw 'Delivery folder exists; preserve it and supply a fresh OutputDirectory.'}
function Digest([string]$file){
    $stream=[IO.File]::OpenRead($file);$sha=[Security.Cryptography.SHA256]::Create()
    try{([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}finally{$stream.Dispose();$sha.Dispose()}
}
$apk=Join-Path $root 'release\mobile\xiquan-mobile-ordering-1.2.9.apk'
$apkHash=Digest $apk
if($apkHash-cne 'd5fdab05253d009319147e6e3775d5d667f2b8a13464cbc44c0caf2130a2472d'){throw 'Current reviewed Android bytes differ; no fictitious APK rebuild.'}
$oldApi=$env:VITE_API_BASE_URL;$oldBuild=$env:VITE_BUILD_ID;$oldModules=$env:PSModulePath
try{
    $env:PSModulePath=(Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\Modules')+';'+$oldModules
    $env:VITE_API_BASE_URL='https://api.pqxqxy.xyz/api';$env:VITE_BUILD_ID=$commit
    foreach($area in @('client','mobile')){
        Push-Location -LiteralPath (Join-Path $root $area)
        try{& npm.cmd run build | Out-Host;if($LASTEXITCODE-ne 0){throw ('Frontend failed: '+$area)}}finally{Pop-Location}
    }
    $webVersion=[ordered]@{buildId=$commit;required=$false;releaseNotes=@('增加实体卡消费功能');publicationState='pending'}
    [IO.File]::WriteAllText((Join-Path $root 'client\dist\version.json'),($webVersion|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    $source=& (Join-Path $PSScriptRoot 'build-operations-source.ps1') -SourceRoot $root -Desktop051 -AssetSourceCommit $commit
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.5.1' -BuildId $buildId -Targets $targets -PublicKeyPath $public -OfflineRuntimeCache $cache -SkipRenderer
    & node.exe (Join-Path $PSScriptRoot 'lib\reviewed-source.cjs') $root $commit
    if($LASTEXITCODE-ne 0){throw 'Source changed while building; retain artifacts, do not deliver.'}
    $release=Join-Path $root ('release\windows\0.5.1\'+$buildId)
    & node.exe (Join-Path $PSScriptRoot 'lib\desktop-051.cjs') verify-candidates $release
    if($LASTEXITCODE-ne 0){throw 'Actual packaged identities failed.'}
    [void](New-Item -ItemType Directory -Path $OutputDirectory)
    foreach($id in $targets){Copy-Item -LiteralPath (Join-Path $release ($id+'\Xiquan-Bathhouse-Setup-0.5.1-'+$id+'.exe')) -Destination $OutputDirectory}
    Copy-Item -LiteralPath $source.ZipPath -Destination $OutputDirectory
    $wrappers=@{'desktop-051-deploy-entry.ps1'='01-部署云端.ps1';'desktop-051-publish-entry.ps1'='02-签名并发布桌面更新.ps1';'desktop-051-verify-entry.ps1'='03-验证三端与更新.ps1'}
    foreach($name in $wrappers.Keys){
        $text=[IO.File]::ReadAllText((Join-Path $PSScriptRoot $name),[Text.Encoding]::UTF8)
        [IO.File]::WriteAllText((Join-Path $OutputDirectory $wrappers[$name]),$text,[Text.UTF8Encoding]::new($true))
    }
    Copy-Item -LiteralPath (Join-Path $root 'docs\releases\desktop-0.5.1.md') -Destination (Join-Path $OutputDirectory 'README-完整PowerShell.md')
    [IO.File]::WriteAllText((Join-Path $OutputDirectory '更新日志.txt'),"0.5.1`r`n1. 增加实体卡消费功能`r`n",[Text.UTF8Encoding]::new($true))
    $records=@(Get-ChildItem -LiteralPath $OutputDirectory -File|Sort-Object Name|ForEach-Object{[ordered]@{file=$_.Name;size=$_.Length;sha256=(Digest $_.FullName)}})
    $delivery=[ordered]@{Version='0.5.1';ProjectRoot=$root;ReleaseRoot=$release;OutputDirectory=$OutputDirectory;SourceCommit=$commit;BuildId=$buildId;BuiltAt=[DateTimeOffset]::Now.ToString('o');PublicationState='pending';SourceZipFile=(Split-Path -Leaf $source.ZipPath);SourceSha256=$source.Sha256;Targets=$targets;Files=$records;AndroidVersion='1.2.9';AndroidVersionCode=16;AndroidApkPath=$apk;AndroidSha256=$apkHash;CompletionToolSha256=(Digest (Join-Path $root 'deploy\cloud\scripts\desktop_051_completion.py'));CloudChanged=$false;UpdateSignature='pending-original-key';ManualDevices='not-tested'}
    [IO.File]::WriteAllText((Join-Path $OutputDirectory '交付信息.json'),($delivery|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'SHA256SUMS.txt'),(($records|ForEach-Object{$_.sha256+'  '+$_.file})-join "`n"),[Text.UTF8Encoding]::new($false))
    & node.exe (Join-Path $PSScriptRoot 'lib\desktop-051.cjs') verify-delivery $OutputDirectory
    if($LASTEXITCODE-ne 0){throw 'Delivery byte verification failed.'}
    [pscustomobject]@{OutputDirectory=$OutputDirectory;SourceCommit=$commit;ReleaseRoot=$release;CloudChanged=$false;UpdateSignature='pending-original-key'}
}finally{$env:VITE_API_BASE_URL=$oldApi;$env:VITE_BUILD_ID=$oldBuild;$env:PSModulePath=$oldModules}
