[CmdletBinding()]
param(
    [string]$PublicKeyPath = 'F:\溪泉洗浴系统\release\windows\0.4.4\stock-fast-20261005-6c1e397a\release-public-key.pem',
    [string]$OfflineRuntimeCache = 'F:\溪泉洗浴系统\release\runtime-cache\stock-20261005',
    [string]$BuildId = ('desktop047-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)),
    [string]$OutputDirectory = 'F:\溪泉洗浴系统\最新版安装包-报表库存升级-0.4.7',
    [switch]$DryRun
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path -Parent $PSScriptRoot
$targets=@('win10-x86','win10-x64','win11-x86','win11-x64')
$check=@'
const path=require('node:path'),root=process.argv[1];
const actual=require(path.join(root,'client/build/windows-pack.cjs')).publicTrust(process.argv[2]);
const trust=require(path.join(root,'scripts/lib/operations-release.cjs')).trust;
if(actual.keyId!==trust.keyId||actual.publicKeyPem!==trust.publicKeyPem)throw Error('Original update public key required');
if(require(path.join(root,'client/package.json')).version!=='0.4.7')throw Error('Source version mismatch');
'@
& node.exe -e $check $root $PublicKeyPath
if($LASTEXITCODE-ne 0){throw 'Public build preflight failed.'}
if($DryRun){
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.4.7' -BuildId $BuildId -Targets $targets -PublicKeyPath $PublicKeyPath -OfflineRuntimeCache $OfflineRuntimeCache -DryRun
    return
}
if(Test-Path -LiteralPath $OutputDirectory){throw 'Delivery folder exists; use a fresh OutputDirectory. Existing files are retained.'}
$commit=(& git.exe -C $root rev-parse HEAD).Trim()
& git.exe -C $root diff --quiet HEAD --
if($LASTEXITCODE-ne 0){throw 'Commit reviewed source changes before building.'}
$oldApi=$env:VITE_API_BASE_URL; $oldBuild=$env:VITE_BUILD_ID
try{
    $env:VITE_API_BASE_URL='https://api.pqxqxy.xyz/api'; $env:VITE_BUILD_ID=$commit
    foreach($area in @('client','mobile')){
        Push-Location -LiteralPath (Join-Path $root $area)
        try{ & npm.cmd run build | Out-Host; if($LASTEXITCODE-ne 0){throw ('Frontend build failed: '+$area)} }
        finally{Pop-Location}
    }
    $webVersion=[ordered]@{buildId=$commit;required=$false;releaseNotes=@('1. 给前台收银和库管增补“经营报表”权限','2. “经营报表”UI优化','3. “库存管理”界面 UI优化','4. 库存预警值设置为商品入库数量的15%');publishedAt=[DateTimeOffset]::Now.ToString('o')}
    [IO.File]::WriteAllText((Join-Path $root 'client\dist\version.json'),($webVersion | ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
    $source=& (Join-Path $PSScriptRoot 'build-operations-source.ps1') -SourceRoot $root
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.4.7' -BuildId $BuildId -Targets $targets -PublicKeyPath $PublicKeyPath -OfflineRuntimeCache $OfflineRuntimeCache -SkipRenderer
    & git.exe -C $root diff --quiet HEAD --
    if($LASTEXITCODE-ne 0 -or (& git.exe -C $root rev-parse HEAD).Trim()-ne $commit){throw 'Source changed during build; retain artifacts, do not deliver.'}
    $release=Join-Path $root ('release\windows\0.4.7\'+$BuildId)
    [void](New-Item -ItemType Directory -Path $OutputDirectory)
    foreach($target in $targets){
        $file=Join-Path $release ($target+'\Xiquan-Bathhouse-Setup-0.4.7-'+$target+'.exe')
        Copy-Item -LiteralPath $file -Destination $OutputDirectory
    }
    Copy-Item -LiteralPath $source.ZipPath -Destination $OutputDirectory
    Copy-Item -LiteralPath (Join-Path $root 'docs\releases\2026-10-07-desktop-047.md') -Destination $OutputDirectory
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'desktop-047-deploy-entry.ps1') -Destination (Join-Path $OutputDirectory '01-部署云端.ps1')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'desktop-047-publish-entry.ps1') -Destination (Join-Path $OutputDirectory '02-签名并发布桌面更新.ps1')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'desktop-047-android-entry.ps1') -Destination (Join-Path $OutputDirectory '03-构建并发布安卓应用内更新.ps1')
    $delivery=[ordered]@{ProjectRoot=$root;ReleaseRoot=$release;OutputDirectory=$OutputDirectory;SourceCommit=$commit;SourceZipFile=(Split-Path -Leaf $source.ZipPath);SourceSha256=$source.Sha256;Version='0.4.7';Targets=$targets;CloudChanged=$false;UpdateSignature='pending-original-key'}
    # Generated metadata, not configuration or credentials. Never include any key/password.
    [IO.File]::WriteAllText((Join-Path $OutputDirectory '交付信息.json'),($delivery | ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($true))
    [pscustomobject]@{ReleaseRoot=$release;OutputDirectory=$OutputDirectory;SourceCommit=$commit;SourceZip=$source.ZipPath;SourceSha256=$source.Sha256;UpdateSignature='pending-original-key';CloudChanged=$false}
}finally{$env:VITE_API_BASE_URL=$oldApi;$env:VITE_BUILD_ID=$oldBuild}
