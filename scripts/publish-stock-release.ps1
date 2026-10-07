[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot,[Parameter(Mandatory)][string]$PreviousApkPath,
    [string]$EcsTarget = 'root@39.96.217.210', [switch]$StageOnly,[switch]$DryRun)
$ErrorActionPreference = 'Stop'
& node.exe (Join-Path $PSScriptRoot 'lib\stock-release.cjs') validate $ReleaseRoot production $PreviousApkPath
if ($LASTEXITCODE -ne 0) { throw 'Formal stock release gates failed; no SSH/SCP performed.' }
& (Join-Path $PSScriptRoot 'publish-windows-release.ps1') -ReleaseRoot $ReleaseRoot -EcsTarget $EcsTarget -StageOnly:$StageOnly -DryRun:$DryRun -Targets @('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64')
