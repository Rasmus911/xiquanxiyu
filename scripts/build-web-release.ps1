[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BuildId,

    [string[]]$ReleaseNotes = @('Web client experience and stability update'),

    [switch]$Required
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($BuildId -notmatch '^[A-Za-z0-9._-]+$') {
    throw 'BuildId may contain only letters, numbers, dot, underscore and hyphen.'
}

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$clientRoot = Join-Path $projectRoot 'client'
$distRoot = Join-Path $clientRoot 'dist'
$deployParent = Join-Path $projectRoot 'deploy\cloud'
$deployRoot = Join-Path $deployParent 'web'
$stageRoot = Join-Path $deployParent ("web.stage." + [guid]::NewGuid().ToString('N'))
$backupRoot = Join-Path $deployParent ("web.backup." + [guid]::NewGuid().ToString('N'))
$publishedAt = [DateTimeOffset]::Now.ToString('o')

function Assert-ChildPath {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Parent)
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $resolvedParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the deployment directory: $resolvedPath"
    }
}

Assert-ChildPath -Path $stageRoot -Parent $deployParent
Assert-ChildPath -Path $backupRoot -Parent $deployParent
Assert-ChildPath -Path $deployRoot -Parent $deployParent

$previousApiUrl = $env:VITE_API_BASE_URL
$previousBuildId = $env:VITE_BUILD_ID
try {
    $env:VITE_API_BASE_URL = 'https://api.pqxqxy.xyz/api'
    $env:VITE_BUILD_ID = $BuildId
    Push-Location $clientRoot
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Web client build failed with exit code $LASTEXITCODE." }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:VITE_API_BASE_URL = $previousApiUrl
    $env:VITE_BUILD_ID = $previousBuildId
}

if (-not (Test-Path -LiteralPath (Join-Path $distRoot 'index.html') -PathType Leaf)) {
    throw 'Web build did not produce dist/index.html.'
}

$version = [ordered]@{
    buildId = $BuildId
    required = [bool]$Required
    releaseNotes = @($ReleaseNotes | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    publishedAt = $publishedAt
}
$versionJson = $version | ConvertTo-Json -Depth 5
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $distRoot 'version.json'), $versionJson + [Environment]::NewLine, $utf8)

try {
    New-Item -ItemType Directory -Path $stageRoot | Out-Null
    Get-ChildItem -LiteralPath $distRoot -Force | Copy-Item -Destination $stageRoot -Recurse -Force
    [IO.File]::ReadAllText(
        (Join-Path $stageRoot 'version.json'),
        [Text.Encoding]::UTF8
    ) | ConvertFrom-Json | Out-Null

    if (Test-Path -LiteralPath $deployRoot) {
        Move-Item -LiteralPath $deployRoot -Destination $backupRoot
    }
    try {
        Move-Item -LiteralPath $stageRoot -Destination $deployRoot
    }
    catch {
        if ((Test-Path -LiteralPath $backupRoot) -and -not (Test-Path -LiteralPath $deployRoot)) {
            Move-Item -LiteralPath $backupRoot -Destination $deployRoot
        }
        throw
    }

    if (Test-Path -LiteralPath $backupRoot) {
        Remove-Item -LiteralPath $backupRoot -Recurse -Force
    }
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}

Write-Host "Web release $BuildId built successfully:" -ForegroundColor Green
Write-Host $deployRoot
Write-Host "Version manifest: $(Join-Path $deployRoot 'version.json')"
