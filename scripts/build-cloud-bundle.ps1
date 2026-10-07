[CmdletBinding()]
param([switch]$IncludeDesktopUpdate)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib\cloud-archive.ps1')
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$releaseDir = Join-Path $projectRoot 'release\cloud'
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("xiquan-cloud-" + [Guid]::NewGuid().ToString('N'))
$bundleRoot = Join-Path $stageRoot 'xiquan'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$zipPath = Join-Path $releaseDir "xiquan-cloud-$timestamp.zip"

$include = @(
    'server\app',
    'server\migrations',
    'server\Dockerfile',
    'server\.dockerignore',
    'server\docker-entrypoint.sh',
    'server\requirements.txt',
    'server\run.py',
    'deploy\cloud\docker-compose.prod.yml',
    'deploy\cloud\.env.example',
    'deploy\cloud\nginx',
    'deploy\cloud\scripts',
    'deploy\cloud\mobile',
    'deploy\cloud\releases',
    'deploy\cloud\web'
)

try {
    New-Item -ItemType Directory -Path $bundleRoot -Force | Out-Null
    foreach ($relativePath in $include) {
        $source = Join-Path $projectRoot $relativePath
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Required deployment file not found: $source"
        }
        $destination = Join-Path $bundleRoot $relativePath
        $parent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
    }

    if ($IncludeDesktopUpdate) {
        $updatesSource = Join-Path $projectRoot 'deploy\cloud\updates'
        $manifestPath = Join-Path $updatesSource 'latest.yml'
        $manifestText = Get-Content -LiteralPath $manifestPath -Raw
        $installerName = [regex]::Match($manifestText, '(?m)^path:\s*(Xiquan-Bathhouse-Setup-\d+\.\d+\.\d+\.exe)\s*$').Groups[1].Value
        $updateVersion = [regex]::Match($manifestText, '(?m)^version:\s*(\d+\.\d+\.\d+)\s*$').Groups[1].Value
        $policy = Get-Content -LiteralPath (Join-Path $projectRoot 'deploy\cloud\releases\client-policy.json') -Raw | ConvertFrom-Json
        if (-not $installerName -or $updateVersion -ne [string]$policy.desktop.latestVersion) {
            throw 'Desktop update files and release policy are not staged consistently. Use publish-electron-update.ps1 -StageOnly first.'
        }
        $installerPath = Join-Path $updatesSource $installerName
        if ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$policy.desktop.sha256) {
            throw 'Staged desktop installer checksum does not match the release policy.'
        }
        $updatesDestination = Join-Path $bundleRoot 'deploy\cloud\updates'
        New-Item -ItemType Directory -Path $updatesDestination -Force | Out-Null
        foreach ($name in @('latest.yml', $installerName, "$installerName.blockmap")) {
            Copy-Item -LiteralPath (Join-Path $updatesSource $name) -Destination (Join-Path $updatesDestination $name) -Force
        }
    }

    # Never include the production secrets in a release bundle.
    $secretEnv = Join-Path $bundleRoot 'deploy\cloud\.env'
    if (Test-Path -LiteralPath $secretEnv) {
        Remove-Item -LiteralPath $secretEnv -Force
    }
    $generatedNginxConfig = Join-Path $bundleRoot 'deploy\cloud\nginx\active.conf'
    if (Test-Path -LiteralPath $generatedNginxConfig) {
        Remove-Item -LiteralPath $generatedNginxConfig -Force
    }

    Get-ChildItem -LiteralPath $bundleRoot -Directory -Filter '__pycache__' -Recurse |
        Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $bundleRoot -File -Recurse |
        Where-Object { $_.Extension -in @('.pyc', '.pyo') } |
        Remove-Item -Force

    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    New-CloudReleaseArchive -SourceDirectory $bundleRoot -DestinationPath $zipPath
    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$zipPath.sha256" -Value "$hash  $(Split-Path -Leaf $zipPath)" -Encoding ascii

    Write-Host "Cloud deployment bundle created:" -ForegroundColor Green
    Write-Host $zipPath
    Write-Host "SHA256: $hash"
}
finally {
    $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $resolvedStage = [System.IO.Path]::GetFullPath($stageRoot)
    if ($resolvedStage.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedStage)) {
        try { Remove-Item -LiteralPath $resolvedStage -Recurse -Force -ErrorAction Stop }
        catch { Write-Warning "Temporary staging is still in use and was retained: $resolvedStage. No existing release or application data was removed." }
    }
}
