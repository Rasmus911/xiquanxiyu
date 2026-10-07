$ErrorActionPreference = "Stop"
$serverDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\server")).Path
Set-Location -LiteralPath $serverDirectory
& ".\.venv\Scripts\python.exe" run.py

