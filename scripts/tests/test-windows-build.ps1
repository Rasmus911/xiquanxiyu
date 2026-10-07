$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'test-windows-tools.ps1') -Group build
