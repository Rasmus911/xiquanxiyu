[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EcsTarget,

    [string]$RemoteCloudDir = '/opt/xiquan/xiquan/deploy/cloud',

    [string]$PublicBaseUrl = 'https://api.pqxqxy.xyz',

    [switch]$StageOnly,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($EcsTarget -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9.\[\]:_-]+$') {
    throw 'EcsTarget must look like root@1.2.3.4 or ubuntu@server.example.com.'
}
if ($RemoteCloudDir -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemoteCloudDir -match '/\.\.?(/|$)') {
    throw 'RemoteCloudDir must be a simple absolute Linux path.'
}
try { $publicUri = [Uri]$PublicBaseUrl } catch { throw 'PublicBaseUrl must be a valid HTTPS URL.' }
if ($publicUri.Scheme -ne 'https' -or $publicUri.UserInfo) { throw 'PublicBaseUrl must be a public HTTPS URL.' }

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$webRoot = Join-Path $projectRoot 'deploy\cloud\web'
$versionPath = Join-Path $webRoot 'version.json'
$indexPath = Join-Path $webRoot 'index.html'
$policyPath = Join-Path $projectRoot 'deploy\cloud\releases\client-policy.json'
$policyHelper = Join-Path $projectRoot 'scripts\lib\release-policy.ps1'
. $policyHelper

foreach ($file in @($versionPath, $indexPath, $policyPath)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required web release file not found: $file" }
}
$version = [IO.File]::ReadAllText($versionPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
$buildId = [string]$version.buildId
if ($buildId -notmatch '^[A-Za-z0-9._-]+$') { throw "Invalid web buildId: $buildId" }
$indexText = Get-Content -LiteralPath $indexPath -Raw
$assetMatches = [regex]::Matches($indexText, '(?:\./|/app/)?assets/[A-Za-z0-9._-]+')
$assets = @($assetMatches | ForEach-Object { $_.Value -replace '^(?:\./|/app/)', '' } | Sort-Object -Unique)
if (-not $assets.Count) { throw 'Web index.html does not reference any hashed assets.' }
foreach ($asset in $assets) {
    if (-not (Test-Path -LiteralPath (Join-Path $webRoot $asset) -PathType Leaf)) {
        throw "Referenced web asset is missing: $asset"
    }
}

$release = @{
    buildId = $buildId
    required = [bool]$version.required
    releaseNotes = @($version.releaseNotes | ForEach-Object { [string]$_ })
    publishedAt = [string]$version.publishedAt
}

Write-Host "Build ID: $buildId"
Write-Host "Web root: $webRoot"
Write-Host "Public URL: $($publicUri.AbsoluteUri.TrimEnd('/'))/app/"
Write-Host "Assets: $($assets.Count)"
if ($DryRun) {
    Write-Host 'Proposed policy:'
    Write-Host ($release | ConvertTo-Json -Depth 5)
    Write-Host 'Web release dry run passed.' -ForegroundColor Green
    return
}

if ($StageOnly) {
    Update-ClientReleasePolicy -Path $policyPath -Platform web -Release $release
    Write-Host 'Web release policy staged locally. No SSH, upload or ECS changes were made.' -ForegroundColor Green
    return
}

foreach ($command in @('tar.exe', 'scp.exe', 'ssh.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Required command not found: $command" }
}

$remoteWebDir = "$RemoteCloudDir/web"
$remoteReleaseDir = "$RemoteCloudDir/releases"
$archivePath = Join-Path $env:TEMP ("xiquan-web-$buildId-" + [guid]::NewGuid().ToString('N') + '.tar.gz')
$remoteArchive = "$remoteWebDir/web-$buildId.tar.gz.new"
$remoteIndex = "$remoteWebDir/index.html.$buildId.new"
$remoteVersion = "$remoteWebDir/version.json.$buildId.new"
$remotePolicy = "$remoteReleaseDir/client-policy.json.$buildId.new"

try {
    & tar.exe -czf $archivePath --exclude='./index.html' --exclude='./version.json' -C $webRoot .
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the web asset archive.' }

    & ssh.exe $EcsTarget "install -d -m 0755 '$remoteWebDir' '$remoteReleaseDir'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare remote web directories.' }
    & scp.exe $archivePath "${EcsTarget}:$remoteArchive"
    if ($LASTEXITCODE -ne 0) { throw 'Web asset upload failed.' }
    & ssh.exe $EcsTarget "tar -xzf '$remoteArchive' -C '$remoteWebDir' && rm -f '$remoteArchive'"
    if ($LASTEXITCODE -ne 0) { throw 'Web asset extraction failed.' }

    & scp.exe $indexPath "${EcsTarget}:$remoteIndex"
    if ($LASTEXITCODE -ne 0) { throw 'Web index upload failed.' }
    & scp.exe $versionPath "${EcsTarget}:$remoteVersion"
    if ($LASTEXITCODE -ne 0) { throw 'Web version upload failed.' }
    & ssh.exe $EcsTarget "python3 -m json.tool '$remoteVersion' >/dev/null && mv -f '$remoteVersion' '$remoteWebDir/version.json' && mv -f '$remoteIndex' '$remoteWebDir/index.html' && chmod -R a+rX '$remoteWebDir'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not activate the web release.' }

    $publicRoot = $publicUri.AbsoluteUri.TrimEnd('/')
    $publicVersion = Invoke-RestMethod -Uri "$publicRoot/app/version.json" -TimeoutSec 30
    if ([string]$publicVersion.buildId -ne $buildId) { throw 'Published web version does not match the local build.' }
    $publicIndex = Invoke-WebRequest -Uri "$publicRoot/app/" -UseBasicParsing -TimeoutSec 30
    foreach ($asset in $assets) {
        if ($publicIndex.Content -notmatch [regex]::Escape((Split-Path -Leaf $asset))) {
            throw "Published index does not reference $asset"
        }
        $head = Invoke-WebRequest -Uri "$publicRoot/app/$asset" -Method Head -UseBasicParsing -TimeoutSec 30
        if ($head.StatusCode -ne 200) { throw "Published asset returned HTTP $($head.StatusCode): $asset" }
    }

    Update-ClientReleasePolicy -Path $policyPath -Platform web -Release $release
    & scp.exe $policyPath "${EcsTarget}:$remotePolicy"
    if ($LASTEXITCODE -ne 0) { throw 'Release policy upload failed.' }
    & ssh.exe $EcsTarget "python3 -m json.tool '$remotePolicy' >/dev/null && mv -f '$remotePolicy' '$remoteReleaseDir/client-policy.json' && chmod 0644 '$remoteReleaseDir/client-policy.json'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not activate the release policy.' }
    $publicPolicy = Invoke-RestMethod -Uri "$publicRoot/releases/client-policy.json" -TimeoutSec 30
    if ([string]$publicPolicy.web.buildId -ne $buildId) { throw 'Public policy does not point to the new web build.' }
}
finally {
    if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
}

Write-Host "Web release $buildId published successfully." -ForegroundColor Green
Write-Host "$($publicUri.AbsoluteUri.TrimEnd('/'))/app/"
