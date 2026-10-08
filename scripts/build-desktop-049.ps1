[CmdletBinding()]
param(
    [string]$PublicKeyPath,
    [string]$OfflineRuntimeCache,
    [string]$BuildId = ('desktop049-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)),
    [string]$OutputDirectory,
    [switch]$DryRun
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path -Parent $PSScriptRoot
if(-not $PublicKeyPath){$PublicKeyPath=Join-Path $root 'release\trust\release-public-key.pem'}
if(-not $OfflineRuntimeCache){$OfflineRuntimeCache=Join-Path $root 'release\runtime-cache\current-windows'}
if(-not $OutputDirectory){$OutputDirectory=Join-Path $root '最新版安装包-账号注册-0.4.9'}
$targets=@('win10-x86','win10-x64','win11-x86','win11-x64')
$check=@'
const path=require('node:path'),root=process.argv[1];
const actual=require(path.join(root,'client/build/windows-pack.cjs')).publicTrust(process.argv[2]);
const trust=require(path.join(root,'scripts/lib/operations-release.cjs')).trust;
if(actual.keyId!==trust.keyId||actual.publicKeyPem!==trust.publicKeyPem)throw Error('Original update public key required');
if(require(path.join(root,'client/package.json')).version!=='0.4.9')throw Error('Source version mismatch');
'@
& node.exe -e $check $root $PublicKeyPath
if($LASTEXITCODE-ne 0){throw 'Public build preflight failed.'}
if($DryRun){
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.4.9' -BuildId $BuildId -Targets $targets -PublicKeyPath $PublicKeyPath -OfflineRuntimeCache $OfflineRuntimeCache -DryRun
    [pscustomobject]@{Version='0.4.9';Targets=$targets;CloudChanged=$false;UpdateSignature='pending-original-key';OutputDirectory=$OutputDirectory}
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
    $notes=@('新增 账号注册功能')
    $webVersion=[ordered]@{buildId=$commit;required=$false;releaseNotes=$notes;publishedAt=[DateTimeOffset]::Now.ToString('o')}
    [IO.File]::WriteAllText((Join-Path $root 'client\dist\version.json'),($webVersion | ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
    $source=& (Join-Path $PSScriptRoot 'build-operations-source.ps1') -SourceRoot $root
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.4.9' -BuildId $BuildId -Targets $targets -PublicKeyPath $PublicKeyPath -OfflineRuntimeCache $OfflineRuntimeCache -SkipRenderer
    & git.exe -C $root diff --quiet HEAD --
    if($LASTEXITCODE-ne 0 -or (& git.exe -C $root rev-parse HEAD).Trim()-ne $commit){throw 'Source changed during build; retain artifacts, do not deliver.'}
    $release=Join-Path $root ('release\windows\0.4.9\'+$BuildId)
    [void](New-Item -ItemType Directory -Path $OutputDirectory)
    foreach($target in $targets){
        $file=Join-Path $release ($target+'\Xiquan-Bathhouse-Setup-0.4.9-'+$target+'.exe')
        Copy-Item -LiteralPath $file -Destination $OutputDirectory
    }
    Copy-Item -LiteralPath $source.ZipPath -Destination $OutputDirectory
    Copy-Item -LiteralPath (Join-Path $root 'docs\releases\2026-10-08-desktop-049.md') -Destination $OutputDirectory
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'desktop-049-deploy-entry.ps1') -Destination (Join-Path $OutputDirectory '01-部署云端.ps1')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'desktop-049-publish-entry.ps1') -Destination (Join-Path $OutputDirectory '02-签名并发布桌面更新.ps1')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'desktop-049-android-entry.ps1') -Destination (Join-Path $OutputDirectory '03-构建并发布安卓应用内更新.ps1')
    $delivery=[ordered]@{ProjectRoot=$root;ReleaseRoot=$release;OutputDirectory=$OutputDirectory;SourceCommit=$commit;SourceZipFile=(Split-Path -Leaf $source.ZipPath);SourceSha256=$source.Sha256;Version='0.4.9';Targets=$targets;CloudChanged=$false;UpdateSignature='pending-original-key'}
    [IO.File]::WriteAllText((Join-Path $OutputDirectory '交付信息.json'),($delivery | ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($true))
    [pscustomobject]@{ReleaseRoot=$release;OutputDirectory=$OutputDirectory;SourceCommit=$commit;SourceZip=$source.ZipPath;SourceSha256=$source.Sha256;UpdateSignature='pending-original-key';CloudChanged=$false}
}finally{$env:VITE_API_BASE_URL=$oldApi;$env:VITE_BUILD_ID=$oldBuild}
