[CmdletBinding()]
param([string]$SourceRoot = (Join-Path $PSScriptRoot '..'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath $SourceRoot).Path
$helper = Join-Path $PSScriptRoot 'lib\stock-source.cjs'
$before = & node.exe $helper inspect $root
if ($LASTEXITCODE -ne 0) { throw 'Stock source must be committed before building assets.' }
$contract = $before | ConvertFrom-Json
$oldBuild = $env:VITE_BUILD_ID; $oldApi = $env:VITE_API_BASE_URL
try {
    $env:VITE_BUILD_ID = $contract.source_commit
    $env:VITE_API_BASE_URL = 'https://api.pqxqxy.xyz/api'
    foreach ($area in @('client','mobile')) {
        $dist = Join-Path $root ($area + '\dist')
        if (Test-Path -LiteralPath $dist) {
            foreach ($entry in @((Get-Item -LiteralPath $dist -Force)) + @(Get-ChildItem -LiteralPath $dist -Force -Recurse)) {
                if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked frontend build path forbidden.' }
            }
        }
        Push-Location -LiteralPath (Join-Path $root $area)
        try {
            & npm.cmd run build | Out-Host
            if ($LASTEXITCODE -ne 0) { throw ('Fresh frontend build failed: ' + $area) }
        } finally { Pop-Location }
    }
    $after = & node.exe $helper inspect $root
    if ($LASTEXITCODE -ne 0 -or $after -cne $before) { throw 'Source changed during fresh asset builds.' }
    $result = & (Join-Path $PSScriptRoot 'build-operations-source.ps1') -SourceRoot $root -Stock -AssetSourceCommit $contract.source_commit
    $readback = & node.exe $helper archive $result.ZipPath $contract.source_commit
    if ($LASTEXITCODE -ne 0 -or -not $readback) { throw 'Stock SOURCE/WEB readback failed; retain evidence.' }
    $verified = $readback | ConvertFrom-Json
    if ($verified.source_commit -cne $contract.source_commit) { throw 'Stock SOURCE/WEB readback identity differs.' }
    $result
} finally { $env:VITE_BUILD_ID = $oldBuild; $env:VITE_API_BASE_URL = $oldApi }
