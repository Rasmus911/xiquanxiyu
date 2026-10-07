[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot,[Parameter(Mandatory)][string]$PrivateKeyPath,
    [Parameter(Mandatory)][string]$ApkPath,[Parameter(Mandatory)][string]$PreviousApkPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$helper = Join-Path $PSScriptRoot 'lib\stock-release.cjs'
& node.exe $helper validate $ReleaseRoot | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Candidate verification failed before any private input.' }
& (Join-Path $PSScriptRoot 'lib\stock-mobile.ps1') -ApkPath $ApkPath -PreviousApkPath $PreviousApkPath | Out-Null
$planText = & node.exe $helper signing-plan
if ($LASTEXITCODE -ne 0) { throw 'Fresh all-six original-trust policy verification failed. No sequence or bootstrap inferred.' }
$plan = $planText | ConvertFrom-Json
$proof = Join-Path $ReleaseRoot ('previous-policies-' + [guid]::NewGuid().ToString('N') + '.json')
[IO.File]::WriteAllText($proof,$planText,[Text.UTF8Encoding]::new($false))
foreach ($row in $plan.previous) {
    & (Join-Path $PSScriptRoot 'sign-windows-release.ps1') -ReleaseRoot $ReleaseRoot -PrivateKeyPath $PrivateKeyPath -Sequence $plan.sequence -MinimumVersion $row.minimum_version -Targets @($row.target) -ReleaseNotes @('Independent stock and manual consumables upgrade; cashier/inventory re-login required')
}
& node.exe $helper finalize $ReleaseRoot $ApkPath $PreviousApkPath
if ($LASTEXITCODE -ne 0) { throw 'Formal verification incomplete; no upload performed. Retain signing evidence.' }
