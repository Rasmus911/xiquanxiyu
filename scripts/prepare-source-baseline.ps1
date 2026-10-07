[CmdletBinding()]
param([switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectRoot
try {
    & node.exe (Join-Path $PSScriptRoot 'lib\source-security.cjs')
    if ($LASTEXITCODE -ne 0) { throw 'Source safety check failed. No files were staged.' }
    if (-not $ValidateOnly) {
        Write-Host 'Validation only: inspect the allowlist before adding files to Git.'
    }
    Write-Host 'Private config, signing keys, old SSH helpers and installers are excluded.'
} finally { Pop-Location }
