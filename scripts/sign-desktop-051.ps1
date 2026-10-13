[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot,[Parameter(Mandatory)][string]$PrivateKeyPath)
$ErrorActionPreference='Stop'
$raw=& node.exe (Join-Path $PSScriptRoot 'lib\desktop-051.cjs') plan
if($LASTEXITCODE-ne 0){throw 'Live original policies unavailable; no guessed sequence or signature.'}
$plan=($raw-join "`n")|ConvertFrom-Json
& node.exe (Join-Path $PSScriptRoot 'lib\desktop-051.cjs') verify-candidates $ReleaseRoot
if($LASTEXITCODE-ne 0){throw 'Exact four candidates failed.'}
foreach($row in $plan.previous){
    & (Join-Path $PSScriptRoot 'sign-windows-release.ps1') -ReleaseRoot $ReleaseRoot -PrivateKeyPath $PrivateKeyPath -Sequence $plan.sequence -MinimumVersion $row.minimum_version -Targets @($row.target) -ReleaseNotes @('增加实体卡消费功能')
}
Write-Host 'Four original-trust policies signed locally; not uploaded.'
