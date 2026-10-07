[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$mobileRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'mobile'))
$distRoot = [System.IO.Path]::GetFullPath((Join-Path $mobileRoot 'dist'))
$deployRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'deploy\cloud\mobile'))
$expectedDeployRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'deploy\cloud\mobile'))

if (-not $deployRoot.Equals($expectedDeployRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $deployRoot.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe mobile deployment path: $deployRoot"
}

Push-Location $mobileRoot
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Mobile web build failed.' }
}
finally {
    Pop-Location
}

New-Item -ItemType Directory -Path $deployRoot -Force | Out-Null
Get-ChildItem -LiteralPath $deployRoot -Force |
    Where-Object { $_.Name -ne 'downloads' } |
    Remove-Item -Recurse -Force
Copy-Item -Path (Join-Path $distRoot '*') -Destination $deployRoot -Recurse -Force

Write-Host "Mobile web release staged:" -ForegroundColor Green
Write-Host $deployRoot
Write-Host "Landing page: https://api.pqxqxy.xyz/mobile/download"
