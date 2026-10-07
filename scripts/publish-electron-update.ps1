[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApiBaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$EcsTarget,

    [string]$RemoteCloudDir = '/opt/xiquan/xiquan/deploy/cloud',

    [string]$MinimumVersion = '0.2.3',

    [string[]]$ReleaseNotes = @('Desktop client experience and stability update'),

    [switch]$Required,

    [switch]$SkipBuild,

    [switch]$StageOnly,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$clientDir = Join-Path $projectRoot 'client'
$releaseDir = Join-Path $clientDir 'release'

try {
    $apiUri = [Uri]$ApiBaseUrl.Trim()
} catch {
    throw 'ApiBaseUrl must be a valid HTTPS URL ending in /api.'
}
if ($apiUri.Scheme -ne 'https' -or $apiUri.UserInfo -or $apiUri.AbsolutePath.TrimEnd('/') -notmatch '/api$') {
    throw 'ApiBaseUrl must be an HTTPS URL ending in /api, for example https://api.example.com/api.'
}
if ($EcsTarget -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9.\[\]:_-]+$') {
    throw 'EcsTarget must look like root@1.2.3.4 or ubuntu@server.example.com.'
}
if ($RemoteCloudDir -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemoteCloudDir -match '/\.\.?(/|$)') {
    throw 'RemoteCloudDir must be a simple absolute Linux path.'
}

foreach ($command in @('npm.cmd', 'scp.exe', 'ssh.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}

$packagePath = Join-Path $clientDir 'package.json'
$package = [System.IO.File]::ReadAllText($packagePath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$version = [string]$package.version
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "package.json version must use x.y.z format. Current value: $version"
}
if ($MinimumVersion -notmatch '^\d+\.\d+\.\d+$' -or [version]$MinimumVersion -gt [version]$version) {
    throw "MinimumVersion must use x.y.z format and cannot exceed $version."
}

if (-not $SkipBuild) {
    $previousApiUrl = $env:VITE_API_BASE_URL
    $previousBuilderCache = $env:ELECTRON_BUILDER_CACHE
    $previousElectronCache = $env:electron_config_cache
    try {
        $env:VITE_API_BASE_URL = $apiUri.AbsoluteUri.TrimEnd('/')
        $env:ELECTRON_BUILDER_CACHE = Join-Path $env:TEMP 'xiquan-electron-builder-cache'
        $env:electron_config_cache = Join-Path $env:TEMP 'xiquan-electron-download-cache'
        Push-Location $clientDir
        try {
            & npm.cmd run electron:build
            if ($LASTEXITCODE -ne 0) { throw "Electron build failed with exit code $LASTEXITCODE" }
        } finally {
            Pop-Location
        }
    } finally {
        $env:VITE_API_BASE_URL = $previousApiUrl
        $env:ELECTRON_BUILDER_CACHE = $previousBuilderCache
        $env:electron_config_cache = $previousElectronCache
    }
}

$manifest = Join-Path $releaseDir 'latest.yml'
$installer = Join-Path $releaseDir "Xiquan-Bathhouse-Setup-$version.exe"
$blockmap = "$installer.blockmap"
foreach ($file in @($manifest, $installer, $blockmap)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Release artifact not found: $file"
    }
}

$manifestText = Get-Content -LiteralPath $manifest -Raw
$manifestVersion = [regex]::Match($manifestText, '(?m)^version:\s*([^\r\n]+)$').Groups[1].Value.Trim()
if ($manifestVersion -ne $version) {
    throw "latest.yml version $manifestVersion does not match package.json version $version."
}
if ($manifestText -notmatch [regex]::Escape((Split-Path -Leaf $installer))) {
    throw 'latest.yml does not reference the expected installer.'
}

$installerHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$publicRoot = $apiUri.GetLeftPart([UriPartial]::Authority) + $apiUri.AbsolutePath.TrimEnd('/').Substring(0, $apiUri.AbsolutePath.TrimEnd('/').Length - 4)
$publicRoot = $publicRoot.TrimEnd('/')
$manifestUrl = "$publicRoot/updates/latest.yml"
$installerUrl = "$publicRoot/updates/$(Split-Path -Leaf $installer)"
$release = @{
    latestVersion = $version
    minimumVersion = $MinimumVersion
    required = [bool]$Required
    downloadUrl = $installerUrl
    sha256 = $installerHash
    releaseNotes = @($ReleaseNotes | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    publishedAt = [DateTimeOffset]::Now.ToString('o')
}

if ($DryRun) {
    Write-Host "Dry run passed for Electron update $version." -ForegroundColor Green
    Write-Host $installer
    Write-Host $blockmap
    Write-Host $manifest
    Write-Host "SHA256: $installerHash"
    Write-Host "Manifest URL: $manifestUrl"
    Write-Host "Installer URL: $installerUrl"
    Write-Host 'Proposed policy:'
    Write-Host ($release | ConvertTo-Json -Depth 5)
    return
}

if ($StageOnly) {
    $localUpdates = Join-Path $projectRoot 'deploy\cloud\updates'
    New-Item -ItemType Directory -Path $localUpdates -Force | Out-Null
    foreach ($artifact in @($installer, $blockmap, $manifest)) {
        Copy-Item -LiteralPath $artifact -Destination (Join-Path $localUpdates (Split-Path -Leaf $artifact)) -Force
    }
    . (Join-Path $projectRoot 'scripts\lib\release-policy.ps1')
    Update-ClientReleasePolicy -Path (Join-Path $projectRoot 'deploy\cloud\releases\client-policy.json') -Platform desktop -Release $release
    Write-Host "Electron $version staged locally. No SSH connection or upload was made." -ForegroundColor Green
    Write-Host "Installer: $installer"
    Write-Host "SHA256: $installerHash"
    return
}

$updatesDir = "$RemoteCloudDir/updates"
$remoteTempManifest = "$updatesDir/latest.yml.$version.new"
$prepareCommand = "install -d -m 0755 '$updatesDir'"
& ssh.exe $EcsTarget $prepareCommand
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the remote updates directory.' }

foreach ($artifact in @($installer, $blockmap)) {
    & scp.exe $artifact "${EcsTarget}:$updatesDir/"
    if ($LASTEXITCODE -ne 0) { throw "Upload failed: $artifact" }
}
& scp.exe $manifest "${EcsTarget}:$remoteTempManifest"
if ($LASTEXITCODE -ne 0) { throw 'Upload failed: latest.yml' }

$activateCommand = "chmod 0644 '$updatesDir/'* && mv -f '$remoteTempManifest' '$updatesDir/latest.yml'"
& ssh.exe $EcsTarget $activateCommand
if ($LASTEXITCODE -ne 0) { throw 'Could not activate latest.yml on the ECS.' }

try {
    $published = Invoke-WebRequest -Uri $manifestUrl -UseBasicParsing -TimeoutSec 20
    # Windows PowerShell returns octet-stream responses as byte[], not text.
    $publishedText = if ($published.Content -is [byte[]]) {
        [System.Text.Encoding]::UTF8.GetString($published.Content)
    } else {
        [string]$published.Content
    }
    $publishedText = $publishedText.TrimStart([char]0xFEFF)
    if ($publishedText -notmatch "(?m)^version:\s*$([regex]::Escape($version))\s*$") {
        throw 'Published latest.yml does not contain the expected version.'
    }
    $installerHead = Invoke-WebRequest -Uri $installerUrl -Method Head -UseBasicParsing -TimeoutSec 30
    if ($installerHead.StatusCode -ne 200) { throw "Published installer returned HTTP $($installerHead.StatusCode)." }
} catch {
    throw "Files were uploaded, but public verification failed at ${manifestUrl}: $($_.Exception.Message)"
}

$policyPath = Join-Path $projectRoot 'deploy\cloud\releases\client-policy.json'
$policyHelper = Join-Path $projectRoot 'scripts\lib\release-policy.ps1'
. $policyHelper
Update-ClientReleasePolicy -Path $policyPath -Platform desktop -Release $release
$remoteReleaseDir = "$RemoteCloudDir/releases"
$remotePolicy = "$remoteReleaseDir/client-policy.json.$version.new"
& ssh.exe $EcsTarget "install -d -m 0755 '$remoteReleaseDir'"
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the remote releases directory.' }
& scp.exe $policyPath "${EcsTarget}:$remotePolicy"
if ($LASTEXITCODE -ne 0) { throw 'Release policy upload failed.' }
& ssh.exe $EcsTarget "python3 -m json.tool '$remotePolicy' >/dev/null && mv -f '$remotePolicy' '$remoteReleaseDir/client-policy.json' && chmod 0644 '$remoteReleaseDir/client-policy.json'"
if ($LASTEXITCODE -ne 0) { throw 'Could not activate the release policy.' }
$publishedPolicy = Invoke-RestMethod -Uri "$publicRoot/releases/client-policy.json" -TimeoutSec 30
if ([string]$publishedPolicy.desktop.latestVersion -ne $version -or [string]$publishedPolicy.desktop.sha256 -ne $installerHash) {
    throw 'Public release policy does not point to the new desktop installer.'
}

Write-Host "Electron update $version published successfully:" -ForegroundColor Green
Write-Host $manifestUrl
