[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApkPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'mobile-asset-policy.ps1')
& (Join-Path $PSScriptRoot 'test-mobile-asset-policy.ps1')

$resolvedApk = (Resolve-Path -LiteralPath $ApkPath).Path
Add-Type -AssemblyName System.IO.Compression.FileSystem

$archive = [System.IO.Compression.ZipFile]::OpenRead($resolvedApk)
try {
    $indexEntry = $archive.GetEntry('assets/public/index.html')
    if (-not $indexEntry) {
        throw 'APK is missing assets/public/index.html.'
    }

    $reader = [System.IO.StreamReader]::new($indexEntry.Open())
    try {
        $indexHtml = $reader.ReadToEnd()
    }
    finally {
        $reader.Dispose()
    }

    if ($indexHtml -match '(?:src|href)="/mobile/') {
        throw 'APK index.html contains /mobile/ URLs, which cannot load inside the Capacitor WebView.'
    }
    if ($indexHtml -notmatch 'src="\./assets/') {
        throw 'APK index.html does not reference its JavaScript bundle with a relative ./assets/ URL.'
    }
    if ($indexHtml -notmatch 'assets/[A-Za-z0-9_-]+-[A-Za-z0-9_-]+\.js') {
        throw 'APK index.html does not reference a hashed JavaScript asset.'
    }

    $assetMatches = [regex]::Matches($indexHtml, '(?:src|href)="\./(?<path>[^"?#]+)')
    foreach ($match in $assetMatches) {
        $entryName = 'assets/public/' + $match.Groups['path'].Value
        if (-not $archive.GetEntry($entryName)) {
            throw "APK index.html references a missing bundled file: $entryName"
        }
    }

    $sourceMaps = @($archive.Entries | Where-Object { $_.FullName -like 'assets/public/*.map' -or $_.FullName -like 'assets/public/assets/*.map' })
    if ($sourceMaps.Count -gt 0) {
        throw 'APK contains development source maps.'
    }

    $webEntries = @($archive.Entries | Where-Object {
        $_.FullName -eq 'assets/public/index.html' -or
        $_.FullName -like 'assets/public/assets/*.js' -or
        $_.FullName -like 'assets/public/assets/*.css'
    })
    foreach ($entry in $webEntries) {
        $webReader = [System.IO.StreamReader]::new($entry.Open())
        try { $webContent = $webReader.ReadToEnd() }
        finally { $webReader.Dispose() }
        if (Test-MobileDevelopmentUrl -Content $webContent -IsIndexHtml:($entry.FullName -eq 'assets/public/index.html')) {
            throw "APK contains a development server URL in $($entry.FullName)."
        }
    }

    if (-not $archive.GetEntry('assets/capacitor.plugins.json')) {
        throw 'APK is missing assets/capacitor.plugins.json.'
    }

    $updaterRegistered = $false
    foreach ($dexEntry in @($archive.Entries | Where-Object { $_.FullName -match '^classes\d*\.dex$' })) {
        $memory = [System.IO.MemoryStream]::new()
        try {
            $dexStream = $dexEntry.Open()
            try { $dexStream.CopyTo($memory) }
            finally { $dexStream.Dispose() }
            $dexText = [System.Text.Encoding]::ASCII.GetString($memory.ToArray())
            if ($dexText.Contains('ApkUpdaterPlugin')) {
                $updaterRegistered = $true
                break
            }
        }
        finally { $memory.Dispose() }
    }
    if (-not $updaterRegistered) {
        throw 'APK does not contain the native ApkUpdater bridge registration.'
    }
}
finally {
    $archive.Dispose()
}

Write-Host 'Capacitor APK asset and native updater verification passed.' -ForegroundColor Green
