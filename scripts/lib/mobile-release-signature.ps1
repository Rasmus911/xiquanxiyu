Set-StrictMode -Version Latest

function Test-MobilePackageIdentity {
    param([string]$PackageLine, [string]$Version, [int]$VersionCode)
    return ($PackageLine -cmatch "name='com\.xiquan\.mobileordering'" -and
        $PackageLine -cmatch ("versionCode='" + $VersionCode + "'") -and
        $PackageLine -cmatch ("versionName='" + [regex]::Escape($Version) + "'"))
}

function Assert-SignedMobileRelease {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ApkPath,
        [Parameter(Mandatory)][string]$PreviousApkPath,
        [string]$ExpectedVersion = '1.2.0',
        [int]$ExpectedVersionCode = 7
    )
    foreach ($path in @($ApkPath, $PreviousApkPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "APK signature reference/input missing: $path" }
    }
    $sdkRoot = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } elseif ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $tools = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'build-tools') -Directory |
        Where-Object { (Test-Path -LiteralPath (Join-Path $_.FullName 'aapt.exe')) -and (Test-Path -LiteralPath (Join-Path $_.FullName 'apksigner.bat')) } |
        Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    if (-not $tools) { throw 'Android aapt/apksigner tools are required to inspect the real APK, not just its filename.' }
    $aapt = Join-Path $tools.FullName 'aapt.exe'
    $apksigner = Join-Path $tools.FullName 'apksigner.bat'
    # Android aapt on Windows cannot reliably open paths containing Chinese characters.
    $aaptCheckPath = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-aapt-' + [guid]::NewGuid().ToString('N') + '.apk')
    try {
        Copy-Item -LiteralPath $ApkPath -Destination $aaptCheckPath
        $badging = & $aapt dump badging $aaptCheckPath
        if ($LASTEXITCODE -ne 0) { throw 'The uploaded APK is not a valid Android package.' }
    }
    finally {
        if (Test-Path -LiteralPath $aaptCheckPath) { Remove-Item -LiteralPath $aaptCheckPath -Force }
    }
    $package = @($badging | Where-Object { $_ -match '^package:' })
    if ($package.Count -ne 1 -or -not (Test-MobilePackageIdentity -PackageLine $package[0] -Version $ExpectedVersion -VersionCode $ExpectedVersionCode)) {
        throw "Actual APK application ID/version does not match $ExpectedVersion/code $ExpectedVersionCode. Renaming an old APK is not an upgrade."
    }
    if (@($badging | Where-Object { $_ -match '^application-debuggable' }).Count) { throw 'Debuggable APKs cannot be published as a production update.' }

    $previousJavaHome = $env:JAVA_HOME
    try {
        if ($env:XIQUAN_ANDROID_JAVA_HOME) { $env:JAVA_HOME = $env:XIQUAN_ANDROID_JAVA_HOME }
        elseif (-not $env:JAVA_HOME) {
            $jdk = Get-ChildItem -Path "$env:ProgramFiles\Microsoft\jdk-21*" -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | Select-Object -First 1
            if ($jdk) { $env:JAVA_HOME = $jdk.FullName }
        }
        function Read-ApkSigner([string]$Path) {
            $signerLines = & $apksigner verify --print-certs $Path
            if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
            $digests = @($signerLines | Where-Object { $_ -match '^Signer #\d+ certificate SHA-256 digest: [0-9a-fA-F]{64}$' })
            if ($digests.Count -ne 1) { throw 'Expected a single original Android release signer.' }
            return ($digests[0] -replace '^.*digest: ', '').ToLowerInvariant()
        }
        $currentSigner = Read-ApkSigner $ApkPath
        $previousSigner = Read-ApkSigner $PreviousApkPath
        if ($currentSigner -ne $previousSigner) {
            throw 'Signing certificate differs from the previous installed release. Stop: use the original certificate, never ask employees to uninstall to bypass this.'
        }
        return [pscustomobject]@{ Version = $ExpectedVersion; VersionCode = $ExpectedVersionCode; CertificateSha256 = $currentSigner }
    }
    finally { $env:JAVA_HOME = $previousJavaHome }
}
