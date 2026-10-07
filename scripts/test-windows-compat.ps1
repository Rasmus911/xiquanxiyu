[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$root = (Resolve-Path -LiteralPath $ReleaseRoot -ErrorAction Stop).Path
& node.exe (Join-Path $project 'client\build\compat-runner.cjs') $root
if ($LASTEXITCODE -ne 0) { throw 'Runtime/module/bridge verification failed; real target OS tests are not implied.' }
