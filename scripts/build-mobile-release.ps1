[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [int]$VersionCode,

    [Parameter(Mandatory = $true)]
    [int]$MinimumVersionCode,

    [string]$ReleaseNotes = 'Android production release',

    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$mobileRoot = Join-Path $projectRoot 'mobile'
$androidRoot = Join-Path $mobileRoot 'android'
$versionPath = Join-Path $mobileRoot 'version.json'
$keystorePath = if ($env:XIQUAN_ANDROID_KEYSTORE) {
    [System.IO.Path]::GetFullPath($env:XIQUAN_ANDROID_KEYSTORE)
} else {
    Join-Path $projectRoot 'private\android\xiquan-mobile-release.jks'
}
$keyAlias = if ($env:XIQUAN_ANDROID_KEY_ALIAS) { $env:XIQUAN_ANDROID_KEY_ALIAS } else { 'xiquan-mobile' }
$releaseRoot = Join-Path $projectRoot 'release\mobile'
$deployMobileRoot = Join-Path $projectRoot 'deploy\cloud\mobile'
$deployDownloadRoot = Join-Path $deployMobileRoot 'downloads'

function Assert-SafeChildPath([string]$Path, [string]$Parent, [string]$Label) {
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $resolvedParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe $Label path: $resolvedPath"
    }
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 8
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $encoding)
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use semantic form such as 1.0.0: $Version"
}
if ($VersionCode -lt 1) {
    throw 'VersionCode must be a positive integer.'
}
if ($MinimumVersionCode -lt 1 -or $MinimumVersionCode -gt $VersionCode) {
    throw 'MinimumVersionCode must be positive and cannot exceed VersionCode.'
}

Assert-SafeChildPath -Path $releaseRoot -Parent $projectRoot -Label 'release output'
Assert-SafeChildPath -Path $deployDownloadRoot -Parent $projectRoot -Label 'deployment output'

$javaHome = if ($env:XIQUAN_ANDROID_JAVA_HOME) {
    [System.IO.Path]::GetFullPath($env:XIQUAN_ANDROID_JAVA_HOME)
} else {
    $jdk = Get-ChildItem -Path "$env:ProgramFiles\Microsoft\jdk-21*" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($jdk) { $jdk.FullName } else { '' }
}
if (-not $javaHome -or -not (Test-Path -LiteralPath (Join-Path $javaHome 'bin\java.exe'))) {
    throw 'JDK 21 was not found. Install Microsoft.OpenJDK.21 or set XIQUAN_ANDROID_JAVA_HOME.'
}

$sdkRoot = if ($env:ANDROID_SDK_ROOT) {
    [System.IO.Path]::GetFullPath($env:ANDROID_SDK_ROOT)
} elseif ($env:ANDROID_HOME) {
    [System.IO.Path]::GetFullPath($env:ANDROID_HOME)
} else {
    Join-Path $env:LOCALAPPDATA 'Android\Sdk'
}
if (-not (Test-Path -LiteralPath (Join-Path $sdkRoot 'platforms\android-35\android.jar'))) {
    throw "Android SDK Platform 35 was not found under $sdkRoot"
}

$buildTools = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'build-tools') -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'apksigner.bat') } |
    Sort-Object { [version]$_.Name } -Descending |
    Select-Object -First 1
if (-not $buildTools) {
    throw "Android Build-Tools with apksigner was not found under $sdkRoot"
}

$apksigner = Join-Path $buildTools.FullName 'apksigner.bat'
$aapt = Join-Path $buildTools.FullName 'aapt.exe'
$gradleWrapper = Join-Path $androidRoot 'gradlew.bat'
$apkAssetTest = Join-Path $PSScriptRoot 'tests\test-mobile-apk-assets.ps1'
if (-not (Test-Path -LiteralPath $gradleWrapper)) { throw "Gradle wrapper not found: $gradleWrapper" }
if (-not (Test-Path -LiteralPath $aapt)) { throw "aapt not found: $aapt" }
if (-not (Test-Path -LiteralPath $apkAssetTest)) { throw "APK asset-path test not found: $apkAssetTest" }
if (-not (Test-Path -LiteralPath $keystorePath)) {
    throw "Release keystore not found: $keystorePath"
}

Write-Host "Version: $Version ($VersionCode), minimum build: $MinimumVersionCode"
Write-Host "JDK: $javaHome"
Write-Host "Android SDK: $sdkRoot"
Write-Host "Build-Tools: $($buildTools.Name)"
Write-Host "Keystore: $keystorePath"
Write-Host "Alias: $keyAlias"

if ($ValidateOnly) {
    Write-Host 'Android release validation passed.' -ForegroundColor Green
    exit 0
}

$versionConfig = [ordered]@{
    version = $Version
    versionCode = $VersionCode
    minimumVersionCode = $MinimumVersionCode
}
Write-Utf8Json -Path $versionPath -Value $versionConfig

$storeSecure = $null
$keySecure = $null
$storeBstr = [IntPtr]::Zero
$keyBstr = [IntPtr]::Zero
$previousJavaHome = $env:JAVA_HOME
$previousAndroidHome = $env:ANDROID_HOME
$previousAndroidSdkRoot = $env:ANDROID_SDK_ROOT
$previousKeystore = $env:XIQUAN_ANDROID_KEYSTORE
$previousAlias = $env:XIQUAN_ANDROID_KEY_ALIAS
$previousStorePassword = $env:XIQUAN_ANDROID_STORE_PASSWORD
$previousKeyPassword = $env:XIQUAN_ANDROID_KEY_PASSWORD

try {
    $env:JAVA_HOME = $javaHome
    $env:ANDROID_HOME = $sdkRoot
    $env:ANDROID_SDK_ROOT = $sdkRoot
    $env:XIQUAN_ANDROID_KEYSTORE = $keystorePath
    $env:XIQUAN_ANDROID_KEY_ALIAS = $keyAlias

    if (-not $env:XIQUAN_ANDROID_STORE_PASSWORD) {
        $storeSecure = Read-Host 'Enter the Android release keystore password' -AsSecureString
        $storeBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($storeSecure)
        $env:XIQUAN_ANDROID_STORE_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($storeBstr)
    }
    if (-not $env:XIQUAN_ANDROID_KEY_PASSWORD) {
        $keySecure = Read-Host 'Enter the Android release key password' -AsSecureString
        $keyBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($keySecure)
        $env:XIQUAN_ANDROID_KEY_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyBstr)
    }

    Push-Location $mobileRoot
    try {
        & npm.cmd test
        if ($LASTEXITCODE -ne 0) { throw 'Mobile tests failed.' }
        & npm.cmd run type-check
        if ($LASTEXITCODE -ne 0) { throw 'Mobile type check failed.' }
        & npm.cmd run native:sync
        if ($LASTEXITCODE -ne 0) { throw 'Capacitor sync failed.' }
    }
    finally {
        Pop-Location
    }

    & $gradleWrapper -p $androidRoot --no-daemon clean assembleRelease
    if ($LASTEXITCODE -ne 0) { throw 'Android release build failed.' }

    $sourceApk = Join-Path $androidRoot 'app\build\outputs\apk\release\app-release.apk'
    if (-not (Test-Path -LiteralPath $sourceApk)) { throw "Release APK was not produced: $sourceApk" }

    & $apkAssetTest -ApkPath $sourceApk
    if ($LASTEXITCODE -ne 0) { throw 'APK contains invalid Capacitor WebView asset paths.' }

    & $apksigner verify --verbose --print-certs $sourceApk
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }

    $apkName = "xiquan-mobile-ordering-$Version.apk"
    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $deployDownloadRoot -Force | Out-Null
    $releaseApk = Join-Path $releaseRoot $apkName
    $deployApk = Join-Path $deployDownloadRoot $apkName
    Copy-Item -LiteralPath $sourceApk -Destination $releaseApk -Force
    Copy-Item -LiteralPath $sourceApk -Destination $deployApk -Force

    $hash = (Get-FileHash -LiteralPath $releaseApk -Algorithm SHA256).Hash.ToLowerInvariant()
    $downloadConfig = [ordered]@{
        version = $Version
        versionCode = $VersionCode
        minimumVersionCode = $MinimumVersionCode
        androidApkUrl = "/mobile/downloads/$apkName"
        sha256 = $hash
        releaseNotes = $ReleaseNotes
    }
    Write-Utf8Json -Path (Join-Path $mobileRoot 'public\download-config.json') -Value $downloadConfig
    New-Item -ItemType Directory -Path $deployMobileRoot -Force | Out-Null
    Write-Utf8Json -Path (Join-Path $deployMobileRoot 'download-config.json') -Value $downloadConfig

    & (Join-Path $PSScriptRoot 'build-mobile-web.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Mobile web release staging failed.' }

    Write-Host 'Android release created successfully.' -ForegroundColor Green
    Write-Host "APK: $releaseApk"
    Write-Host "Deployment APK: $deployApk"
    Write-Host "SHA256: $hash"
}
finally {
    $env:JAVA_HOME = $previousJavaHome
    $env:ANDROID_HOME = $previousAndroidHome
    $env:ANDROID_SDK_ROOT = $previousAndroidSdkRoot
    $env:XIQUAN_ANDROID_KEYSTORE = $previousKeystore
    $env:XIQUAN_ANDROID_KEY_ALIAS = $previousAlias
    $env:XIQUAN_ANDROID_STORE_PASSWORD = $previousStorePassword
    $env:XIQUAN_ANDROID_KEY_PASSWORD = $previousKeyPassword
    if ($storeBstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($storeBstr) }
    if ($keyBstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyBstr) }
    $storeSecure = $null
    $keySecure = $null
}
