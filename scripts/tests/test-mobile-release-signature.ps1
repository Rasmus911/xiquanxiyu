$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '..\lib\mobile-release-signature.ps1')
foreach ($wrongId in @('COM.XIQUAN.MOBILEORDERING', 'com.Xiquan.mobileordering')) {
    if (Test-MobilePackageIdentity -PackageLine "package: name='$wrongId' versionCode='7' versionName='1.2.0'" -Version '1.2.0' -VersionCode 7) {
        throw 'Android application ID comparison must be case-sensitive.'
    }
}
if (-not (Test-MobilePackageIdentity -PackageLine "package: name='com.xiquan.mobileordering' versionCode='7' versionName='1.2.0'" -Version '1.2.0' -VersionCode 7)) {
    throw 'Expected mobile package identity was rejected.'
}
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$previousApk = Join-Path $projectRoot 'release\mobile\xiquan-mobile-ordering-1.1.1.apk'
$debugApk = Join-Path $projectRoot 'mobile\android\app\build\outputs\apk\debug\app-debug.apk'
$valid = Assert-SignedMobileRelease -ApkPath $previousApk -PreviousApkPath $previousApk -ExpectedVersion '1.1.1' -ExpectedVersionCode 6
if ($valid.CertificateSha256 -notmatch '^[0-9a-f]{64}$') { throw 'APK signer fingerprint was not returned.' }
$oldRejected = $false
try { Assert-SignedMobileRelease -ApkPath $previousApk -PreviousApkPath $previousApk | Out-Null }
catch { $oldRejected = $true }
if (-not $oldRejected) { throw 'A real old APK must not pass the new release version check.' }
$debugRejected = $false
try { Assert-SignedMobileRelease -ApkPath $debugApk -PreviousApkPath $previousApk | Out-Null }
catch { $debugRejected = $true }
if (-not $debugRejected) { throw 'A debug APK must not pass production release checks.' }
Write-Host '6 APK checks passed: 3 case-sensitive identity cases and 3 real APK version/signature checks. No passwords or network calls.'
