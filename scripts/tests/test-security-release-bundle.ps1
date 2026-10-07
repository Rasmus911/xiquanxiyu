$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '..\lib\security-release-bundle.ps1')
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-bundle-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
$utf8 = New-Object Text.UTF8Encoding($false)
$checks = 0
function Get-TestHash([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($Value)))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function New-Fixture([string]$Name, [string]$Mutation = '') {
    $exe = 'test-only-not-an-installer'
    $apk = 'test-only-not-an-apk'
    $policy = @{
        schemaVersion = 1
        desktop = @{ latestVersion = '0.4.0'; minimumVersion = '0.4.0'; sha256 = (Get-TestHash $exe); downloadUrl = 'https://api.pqxqxy.xyz/updates/Xiquan-Bathhouse-Setup-0.4.0.exe' }
        android = @{ latestVersion = '1.2.0'; latestVersionCode = 7; minimumVersionCode = 7; sha256 = (Get-TestHash $apk); downloadUrl = 'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.2.0.apk' }
        web = @{ buildId = '20260930-security-040' }
    }
    $mobile = @{ version = '1.2.0'; versionCode = 7; minimumVersionCode = 7; androidApkUrl = '/mobile/downloads/xiquan-mobile-ordering-1.2.0.apk'; sha256 = (Get-TestHash $apk) }
    $web = @{ buildId = '20260930-security-040' }
    if ($Mutation -eq 'old-mobile') { $policy.android.latestVersion = '1.1.1' }
    if ($Mutation -eq 'web-policy') { $policy.web.buildId = 'old-build' }
    if ($Mutation -eq 'mobile-code') { $mobile.versionCode = 6 }
    if ($Mutation -eq 'mobile-minimum') { $mobile.minimumVersionCode = 4 }
    if ($Mutation -eq 'external-download') { $policy.android.downloadUrl = 'https://example.com/malicious.apk' }
    $files = @{
        'xiquan/deploy/cloud/releases/client-policy.json' = ($policy | ConvertTo-Json -Depth 8)
        'xiquan/deploy/cloud/mobile/download-config.json' = ($mobile | ConvertTo-Json)
        'xiquan/deploy/cloud/web/version.json' = ($web | ConvertTo-Json)
        'xiquan/deploy/cloud/web/index.html' = '<html>fixture</html>'
        'xiquan/deploy/cloud/mobile/index.html' = '<html>fixture</html>'
        'xiquan/deploy/cloud/mobile/app/index.html' = '<html>fixture</html>'
        'xiquan/deploy/cloud/updates/latest.yml' = "version: 0.4.0`npath: Xiquan-Bathhouse-Setup-0.4.0.exe`n"
        'xiquan/deploy/cloud/updates/Xiquan-Bathhouse-Setup-0.4.0.exe' = $exe
        'xiquan/deploy/cloud/updates/Xiquan-Bathhouse-Setup-0.4.0.exe.blockmap' = 'fixture'
        'xiquan/deploy/cloud/mobile/downloads/xiquan-mobile-ordering-1.2.0.apk' = $apk
        'xiquan/deploy/cloud/docker-compose.prod.yml' = 'name: xiquan'
        'xiquan/deploy/cloud/scripts/runtime-role.sql' = '-- fixture'
        'xiquan/deploy/cloud/scripts/common.sh' = '# fixture'
        'xiquan/server/Dockerfile' = '# fixture'
        'xiquan/server/app/__init__.py' = '# fixture'
        'xiquan/server/migrations/versions/20260930_security_evidence.py' = '# fixture'
    }
    if ($Mutation -eq 'missing-apk') { $files.Remove('xiquan/deploy/cloud/mobile/downloads/xiquan-mobile-ordering-1.2.0.apk') }
    if ($Mutation -eq 'bad-hash') { $files['xiquan/deploy/cloud/updates/Xiquan-Bathhouse-Setup-0.4.0.exe'] = 'changed' }
    if ($Mutation -eq 'private-env') { $files['xiquan/deploy/cloud/.env'] = 'SECRET=fixture' }
    if ($Mutation -eq 'private-key') { $files['xiquan/private/android/key.jks'] = 'fixture' }
    if ($Mutation -eq 'traversal') { $files['xiquan/../../escape.txt'] = 'fixture' }
    if ($Mutation -eq 'absolute') { $files['/etc/escape.txt'] = 'fixture' }
    $path = Join-Path $fixtureRoot "$Name.zip"
    $archive = [IO.Compression.ZipFile]::Open($path, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($key in $files.Keys) {
            $entry = $archive.CreateEntry($key)
            $writer = New-Object IO.StreamWriter($entry.Open(), $utf8)
            try { $writer.Write([string]$files[$key]) } finally { $writer.Dispose() }
        }
    }
    finally { $archive.Dispose() }
    return $path
}
try {
    $valid = Assert-SecurityReleaseBundle -Path (New-Fixture 'valid')
    if ($valid.DesktopVersion -ne '0.4.0' -or $valid.MobileVersion -ne '1.2.0' -or $valid.WebBuildId -ne '20260930-security-040') {
        throw 'Valid release metadata was not returned correctly.'
    }
    $checks++
    foreach ($mutation in @('old-mobile', 'web-policy', 'mobile-code', 'mobile-minimum', 'external-download', 'missing-apk', 'bad-hash', 'private-env', 'private-key', 'traversal', 'absolute')) {
        $rejected = $false
        try { Assert-SecurityReleaseBundle -Path (New-Fixture $mutation $mutation) | Out-Null }
        catch { $rejected = $true }
        if (-not $rejected) { throw "Unsafe fixture was accepted: $mutation" }
        $checks++
    }
    Write-Host "$checks security release bundle tests passed. No network calls were made."
}
finally {
    $resolvedFixture = [IO.Path]::GetFullPath($fixtureRoot)
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedFixture.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing fixture cleanup outside TEMP.' }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}
