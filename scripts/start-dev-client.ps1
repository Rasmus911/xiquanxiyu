$ErrorActionPreference = "Stop"
$clientDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\client")).Path
Set-Location -LiteralPath $clientDirectory
npm run electron:dev

