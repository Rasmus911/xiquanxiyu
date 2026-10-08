[CmdletBinding()]
param([switch]$StageOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$bundle = Join-Path $PSScriptRoot 'xiquan-stock-SOURCE-WEB-20261005-131735-9db6283a.zip'
$expectedSha = '5d5545aa5f7c0586ecfedc87c987893e6c88b2f4ca0882fd6bc99d767e6a804a'
$expectedCommit = 'c468e73486c864fb732b6d09987d1d23cf222cfe'
$entry = Join-Path $projectRoot 'scripts\invoke-stock-upgrade.ps1'
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw 'Use this delivery inside the original project directory.' }
if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expectedSha) { throw 'SOURCE archive hash mismatch. Nothing uploaded.' }
$common = @{BundlePath=$bundle;ExpectedSha256=$expectedSha;SourceCommit=$expectedCommit}
& $entry @common -Mode preflight -StageOnly
if ($StageOnly) {
    Write-Host 'LOCAL_CHECK_ONLY: no SSH, upload or database changes.'
    return
}
Write-Host 'Uploading the exact SOURCE and running read-only cloud preflight.'
$preflightRecords = @(& $entry @common -Mode preflight | Where-Object {
    $_ -is [pscustomobject] -and $null -ne $_.PSObject.Properties['stage']
})
if ($preflightRecords.Count -ne 1) { throw 'One verified preflight result required. Deployment not started.' }
$stage = [string]$preflightRecords[0].stage
if ($stage -notmatch '^/opt/xiquan-releases/stock-stage-[0-9a-f]{32}$' -or
    $preflightRecords[0].source_commit -cne $expectedCommit -or
    $preflightRecords[0].source_sha256 -cne $expectedSha) { throw 'Stage identity differs. Deployment not started.' }
Write-Host ('Verified stage selected automatically: ' + $stage)
Write-Host 'The next step asks for MAINTENANCE plus the complete source commit.'
Write-Host 'It stops API writes, verifies backups and performs the additive migration.'
& $entry @common -Mode deploy -Stage $stage
Write-Host 'Cloud driver returned successfully. Keep its evidence and job directory.'
Write-Host 'Photo inventory import, signed installer publication and real-device acceptance are separate steps.'
