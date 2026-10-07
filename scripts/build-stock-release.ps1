[CmdletBinding()]
param(
    [string]$PublicKeyPath = 'F:\溪泉洗浴系统\release\windows\0.4.3\operations-offline-20261004-190513-bb38f4aa\release-public-key.pem',
    [string]$OfflineRuntimeCache = 'F:\溪泉洗浴系统\release\runtime-cache\stock-20261005',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')][string]$BuildId = ('stock-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)),
    [string]$OutputDirectory = 'F:\溪泉洗浴系统\最新版安装包-库存升级-0.4.4',
    [string]$WindowsReleaseRoot,
    [string]$WindowsInputsPath,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$targets = @('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64')
$check = @'
const path=require('node:path'),root=process.argv[1];
const {publicTrust}=require(path.join(root,'client/build/windows-pack.cjs'));
const {trust}=require(path.join(root,'scripts/lib/operations-release.cjs'));
const actual=publicTrust(process.argv[2]);if(actual.keyId!==trust.keyId||actual.publicKeyPem.trim()!==trust.publicKeyPem.trim())throw Error('Original public trust required');
'@
& node.exe -e $check $root $PublicKeyPath
if ($LASTEXITCODE -ne 0) { throw 'Stock public trust preflight failed.' }
$before = & node.exe (Join-Path $PSScriptRoot 'lib\stock-source.cjs') inspect $root
if ($LASTEXITCODE -ne 0) { throw 'Stock committed source preflight failed.' }
$contract = $before | ConvertFrom-Json
if ($WindowsReleaseRoot) {
    if (-not $WindowsInputsPath) { throw 'Reused Windows build requires recorded pre/post-build input inventory.' }
    $recorded = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $WindowsInputsPath).Path).Trim().TrimStart([char]0xFEFF)
    $current = & node.exe (Join-Path $PSScriptRoot 'lib\stock-source.cjs') windows-inputs $root
    if ($LASTEXITCODE -ne 0 -or $current -cne $recorded) { throw 'Reused Windows build inputs differ from current committed source.' }
}
if ($DryRun) {
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.4.4' -BuildId $BuildId -Targets $targets -PublicKeyPath $PublicKeyPath -OfflineRuntimeCache $OfflineRuntimeCache -DryRun
    return
}
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Delivery directory already exists; select a fresh output directory.' }
$source = & (Join-Path $PSScriptRoot 'build-stock-source.ps1') -SourceRoot $root
if (-not $WindowsReleaseRoot) {
    & (Join-Path $PSScriptRoot 'build-windows-release.ps1') -Version '0.4.4' -BuildId $BuildId -Targets $targets -PublicKeyPath $PublicKeyPath -OfflineRuntimeCache $OfflineRuntimeCache -SkipRenderer
}
$after = & node.exe (Join-Path $PSScriptRoot 'lib\stock-source.cjs') inspect $root
if ($LASTEXITCODE -ne 0 -or $before -cne $after) { throw 'Source changed during installer builds; do not collect.' }
$releaseRoot = $WindowsReleaseRoot
if (-not $releaseRoot) { $releaseRoot = Join-Path $root ('release\windows\0.4.4\' + $BuildId) }
& node.exe (Join-Path $PSScriptRoot 'lib\stock-release.cjs') collect $releaseRoot $source.ZipPath $contract.source_commit | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $releaseRoot 'stock-manifest.json') -PathType Leaf)) { throw 'Stock candidate collection failed; build evidence retained.' }
& node.exe (Join-Path $PSScriptRoot 'lib\stock-release.cjs') deliver $releaseRoot $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Stock delivery readback failed; evidence retained.' }
Write-Host ('Candidate release root: ' + $releaseRoot + '; formal APK and signed update envelopes pending.')
