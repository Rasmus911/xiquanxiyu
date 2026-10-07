[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PublicKeyPath,
    [string]$OfflineRuntimeCache,
    [string]$PrivateKeyPath = 'F:\溪泉发布密钥\desktop-release-private.pem',
    [string]$PreviousDesktopPolicyPath,
    [int]$Sequence = 0,
    [string]$PreviousApkPath,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')]
    [string]$BuildId = ('operations-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)),
    [switch]$SkipSigning,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$project = Split-Path -Parent $PSScriptRoot
$client = Get-Content -LiteralPath (Join-Path $project 'client\package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$mobile = Get-Content -LiteralPath (Join-Path $project 'mobile\version.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$desktopVersion = [string]$client.version
$mobileVersion = [string]$mobile.version
$publicPath = (Resolve-Path -LiteralPath $PublicKeyPath -ErrorAction Stop).Path
if ((Split-Path -Leaf $publicPath) -match '(?i)private|secret|\.jks$') { throw 'Only the original public release key may be provided here.' }
$preflight = @'
const fs=require('node:fs'),path=require('node:path');const root=process.argv[1];
const {publicTrust}=require(path.join(root,'client/build/windows-pack.cjs'));
const {trust}=require(path.join(root,'scripts/lib/operations-release.cjs'));
const current=publicTrust(process.argv[2]);if(current.keyId!==trust.keyId||current.publicKeyPem!==trust.publicKeyPem)throw Error('Original desktop trust key is required; do not generate a replacement key');
const p=JSON.parse(fs.readFileSync(path.join(root,'client/package.json'))),m=JSON.parse(fs.readFileSync(path.join(root,'mobile/version.json')));
if(p.version!=='0.4.3'||m.version!=='1.2.2'||m.versionCode!==9)throw Error('Reviewed source versions must be 0.4.3 / Android 1.2.2 code 9; newer releases require a reviewed version bump');
'@
& node.exe -e $preflight $project $publicPath
if ($LASTEXITCODE -ne 0) { throw 'Public identity/version preflight failed; stopped before private input or build.' }
if (-not $PreviousApkPath) { $PreviousApkPath = Join-Path $project 'release\mobile\xiquan-mobile-ordering-1.2.1.apk' }
if (-not $SkipSigning) {
    if ($Sequence -lt 1 -or -not $PreviousDesktopPolicyPath) { throw 'Provide an existing signed Win11 policy snapshot and a strictly newer Sequence; do not guess sequence 1.' }
    $previousPolicy = (Resolve-Path -LiteralPath $PreviousDesktopPolicyPath -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $PreviousApkPath -PathType Leaf)) { throw 'Original previously installed APK is required for certificate comparison.' }
    $policyCheck = @'
try{const fs=require('node:fs'),path=require('node:path'),root=process.argv[1];
const {trust}=require(path.join(root,'scripts/lib/operations-release.cjs'));
const {verifySignedRelease}=require(path.join(root,'client/electron/desktop-release.cjs'));
const {compareSemver}=require(path.join(root,'client/electron/update-policy.cjs'));
const {getTarget}=require(path.join(root,'client/electron/target-profiles.cjs'));
// Verify the previous release on its own, then require the requested version to
// be newer below. Using the new version here would reject every older policy.
const release=verifySignedRelease(JSON.parse(fs.readFileSync(process.argv[2],'utf8').replace(/^\uFEFF/,'')),{trust,profile:getTarget('win11-x64'),currentVersion:'0.0.0'});
if(Number(process.argv[3])<=release.sequence||compareSemver(process.argv[4],release.desktop.latestVersion)<=0)throw Error();
console.log('Previous public signature verified; requested version and sequence are newer.');
}catch{console.error('Previous desktop policy signature, version or sequence is invalid; no signing allowed.');process.exitCode=1;}
'@
    & node.exe -e $policyCheck $project $previousPolicy $Sequence $desktopVersion
    if ($LASTEXITCODE -ne 0) { throw 'Previous policy preflight failed.' }
}
if ($ValidateOnly) {
    Write-Host 'Preflight only: Win11 x64 target / original public key / source versions checked. No installers, signing or upload performed.'
    return
}
$focus = Join-Path $project ('最新版安装包-' + $desktopVersion)
if (Test-Path -LiteralPath $focus) { throw ('Output already exists and will not be overwritten: ' + $focus) }
function Run-Step([string]$Name, [scriptblock]$Action) {
    Write-Host ('Checking: ' + $Name)
    & $Action
    if ($LASTEXITCODE -ne 0) { throw ($Name + ' failed. Nothing uploaded; keep existing releases.') }
}
$previousDotenv = $env:PYTHON_DOTENV_DISABLED
$previousApi = $env:VITE_API_BASE_URL
$previousBuild = $env:VITE_BUILD_ID
try {
    $env:PYTHON_DOTENV_DISABLED = '1'
    $env:VITE_API_BASE_URL = 'https://api.pqxqxy.xyz/api'
    $env:VITE_BUILD_ID = $BuildId
    Push-Location -LiteralPath (Join-Path $project 'server')
    try { Run-Step 'backend regression (PG17 real gates are separate)' { & '.\.venv\Scripts\python.exe' -m pytest tests -q -p no:cacheprovider --tb=short } }
    finally { Pop-Location }
    foreach ($area in @('client','mobile')) {
        Push-Location -LiteralPath (Join-Path $project $area)
        try {
            Run-Step ($area + ' tests') { & npm.cmd test }
            Run-Step ($area + ' type check/build') { & npm.cmd run build }
        } finally { Pop-Location }
    }
    Push-Location -LiteralPath $project
    try { Run-Step 'release tooling tests' { & node.exe --test 'scripts/lib/*.node-test.cjs' } }
    finally { Pop-Location }
    foreach ($name in @('test-cloud-archive','test-release-policy','test-mobile-release-signature','test-windows-tools','test-operations-source')) {
        $testScript = Join-Path $PSScriptRoot ('tests\' + $name + '.ps1')
        Run-Step $name { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $testScript }
    }
    Run-Step 'web build identity and version manifest' {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build-web-release.ps1') -BuildId $BuildId
    }
    # The source package is made while tracked source is still unchanged by Android release metadata.
    $source = & (Join-Path $PSScriptRoot 'build-operations-source.ps1')
    if (-not $source -or -not (Test-Path -LiteralPath $source.ZipPath)) { throw 'SOURCE/WEB bundle missing.' }
    $build = @{Version=$desktopVersion;BuildId=$BuildId;Targets=@('win11-x64');PublicKeyPath=$publicPath;SkipRenderer=$true}
    if ($OfflineRuntimeCache) { $build.OfflineRuntimeCache = $OfflineRuntimeCache }
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') @build
    if ($LASTEXITCODE -ne 0) { throw 'Win11 x64 build failed; signing and uploading stopped.' }
    $releaseRoot = Join-Path $project ('release\windows\' + $desktopVersion + '\' + $BuildId)
    if (-not $SkipSigning) {
        & (Join-Path $PSScriptRoot 'sign-windows-release.ps1') -ReleaseRoot $releaseRoot -PrivateKeyPath $PrivateKeyPath -Targets @('win11-x64') `
            -Sequence $Sequence -MinimumVersion $desktopVersion -ReleaseNotes @('修复员工权限、联动点单、正式价目表及套票')
        if ($LASTEXITCODE -ne 0) { throw 'Win11 signing failed; stopped before APK build/upload.' }
        & (Join-Path $PSScriptRoot 'build-mobile-release.ps1') -Version $mobileVersion -VersionCode ([int]$mobile.versionCode) `
            -MinimumVersionCode ([int]$mobile.minimumVersionCode) -ReleaseNotes '员工权限、联动点单、正式价目表及套票升级'
        if ($LASTEXITCODE -ne 0) { throw 'Android release failed; no upload. Keep the already signed desktop build.' }
        . (Join-Path $PSScriptRoot 'lib\mobile-release-signature.ps1')
        $apkPath = Join-Path $project ('release\mobile\xiquan-mobile-ordering-' + $mobileVersion + '.apk')
        $certificate = Assert-SignedMobileRelease -ApkPath $apkPath -PreviousApkPath $PreviousApkPath -ExpectedVersion $mobileVersion -ExpectedVersionCode ([int]$mobile.versionCode)
        if (-not $certificate) { throw 'Original APK certificate was not verified.' }
    }
    & (Join-Path $PSScriptRoot 'build-windows-delivery.ps1') -ReleaseRoot $releaseRoot -Targets @('win11-x64') -Candidate:$SkipSigning
    if ($LASTEXITCODE -ne 0) { throw 'Win11 ZIP verification failed.' }
    [void](New-Item -ItemType Directory -Path $focus)
    $exe = Join-Path $releaseRoot ('win11-x64\Xiquan-Bathhouse-Setup-' + $desktopVersion + '-win11-x64.exe')
    Copy-Item -LiteralPath $exe -Destination $focus
    Copy-Item -LiteralPath $source.ZipPath -Destination $focus
    $status = 'unsigned-desktop-only'
    if (-not $SkipSigning) { Copy-Item -LiteralPath $apkPath -Destination $focus; $status = 'original-signatures-verified' }
    if (-not $SkipSigning) {
        Copy-Item -LiteralPath $apkPath -Destination $releaseRoot
        Copy-Item -LiteralPath $source.ZipPath -Destination $releaseRoot
        $index = Get-Content -LiteralPath (Join-Path $releaseRoot 'delivery-index.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $index.signed -or @($index.targets).Count -ne 1 -or $index.targets[0].profile.targetId -ne 'win11-x64') { throw 'Expected one verified signed Win11 target.' }
        $manifest = [ordered]@{schema=1;source_commit=$source.SourceCommit;desktop_version=$desktopVersion;android_version=$mobileVersion;
            android_version_code=[int]$mobile.versionCode;build_id=$BuildId;trust_key_id=$index.releaseTrust.keyId;signature_status='verified';
            targets=@(@{target='win11-x64';runtime='44.5.1';arch='x64';file=('win11-x64/' + (Split-Path -Leaf $exe));
                sha256=$index.targets[0].artifact.sha256;size=[long]$index.targets[0].artifact.size});
            android=@{file=(Split-Path -Leaf $apkPath);sha256=(Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant();
                size=(Get-Item -LiteralPath $apkPath).Length;certificate_status='verified';certificate_sha256=$certificate.CertificateSha256};
            source_web=@{file=(Split-Path -Leaf $source.ZipPath);sha256=$source.Sha256;size=(Get-Item -LiteralPath $source.ZipPath).Length};
            test_results=@{backend='passed';desktop='passed';mobile='passed';release='passed';pg17_restore='not-tested'};
            real_device_checks=@{windows11='not-tested';android='not-tested';usb_printer='not-tested'}}
        $manifestPath = Join-Path $releaseRoot 'operations-manifest.json'
        [IO.File]::WriteAllText($manifestPath,($manifest | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
        & node.exe (Join-Path $PSScriptRoot 'lib\operations-release.cjs') $releaseRoot
        if ($LASTEXITCODE -ne 0) { throw 'Operations manifest file identity/hash check failed; no upload.' }
        Copy-Item -LiteralPath $manifestPath -Destination $focus
    }
    $location = [ordered]@{schema=1;source_commit=$source.SourceCommit;build_id=$BuildId;desktop_target='win11-x64';
        release_root=$releaseRoot;installer_directory=$focus;source_zip=$source.ZipPath;source_sha256=$source.Sha256;status=$status;
        pending=@('isolated-PG17-role-concurrency-restore','Win11-and-Android-real-device','USB003-printing','user-ECS-deployment');uploaded=$false}
    [IO.File]::WriteAllText((Join-Path $focus 'BUILD-STATUS.json'),($location | ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
    Write-Host ('Installer directory: ' + $focus)
    Write-Host ('Verified desktop release root: ' + $releaseRoot)
    Write-Host ('SOURCE/WEB: ' + $source.ZipPath)
    Write-Host ('SOURCE/WEB SHA256: ' + $source.Sha256)
    Write-Host ('Signature status: ' + $status + '. No files uploaded. Real PG17, devices and cloud rollout remain separate gates.')
} finally {
    $env:PYTHON_DOTENV_DISABLED = $previousDotenv
    $env:VITE_API_BASE_URL = $previousApi
    $env:VITE_BUILD_ID = $previousBuild
}
