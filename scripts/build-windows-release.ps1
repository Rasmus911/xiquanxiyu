[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '0.4.3',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')][string]$BuildId = ('windows-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)),
    [string[]]$Targets = @('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64'),
    [string]$PublicKeyPath,
    [string]$OfflineRuntimeCache,
    [switch]$TestOnly,
    [switch]$SkipRenderer,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
# Publishing keys and optional Authenticode signing are explicit user-only steps.
# Reject implicit builder credentials without logging or reading their contents.
foreach ($signingVariable in @('CSC_LINK','WIN_CSC_LINK','CSC_KEY_PASSWORD','WIN_CSC_KEY_PASSWORD','CSC_NAME')) {
    if ([Environment]::GetEnvironmentVariable($signingVariable)) {
        throw ('Implicit signing configuration detected: ' + $signingVariable + '. Clear it before this public-key-only build; sign explicitly afterwards.')
    }
}
if ($TestOnly -and $PublicKeyPath) { throw 'Select TestOnly OR a public key.' }
if (-not $TestOnly -and -not $PublicKeyPath) { throw 'A public release key is required; use -TestOnly for a compatibility candidate.' }
$node = (Get-Command node.exe -ErrorAction Stop).Source
[void](Get-Command npm.cmd -ErrorAction Stop)
if (-not $DryRun) {
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($project))
    if ($drive.AvailableFreeSpace -lt 4GB) { throw 'At least 4GB of free space is required.' }
}
$nodeArgs = @((Join-Path $project 'client\build\windows-pack.cjs'), '--version', $Version, '--build-id', $BuildId, '--targets', ($Targets -join ','))
if ($TestOnly) { $nodeArgs += '--test-only' }
else { $nodeArgs += @('--public-key', (Resolve-Path -LiteralPath $PublicKeyPath -ErrorAction Stop).Path) }
if ($SkipRenderer) { $nodeArgs += '--skip-renderer' }
if ($OfflineRuntimeCache) {
    if (-not [IO.Path]::IsPathRooted($OfflineRuntimeCache)) { throw 'OfflineRuntimeCache must be an absolute directory.' }
    $nodeArgs += @('--offline-runtime-cache', (Resolve-Path -LiteralPath $OfflineRuntimeCache -ErrorAction Stop).Path)
}
if ($DryRun) { $nodeArgs += '--dry-run' }
$oldDiscovery = $env:CSC_IDENTITY_AUTO_DISCOVERY
try {
    # No automatic use of a certificate/key from this developer machine.
    $env:CSC_IDENTITY_AUTO_DISCOVERY = 'false'
    & $node @nodeArgs
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed. No files were uploaded.' }
    if (-not $DryRun) {
        $indexPath = Join-Path $project ('release\windows\' + $Version + '\' + $BuildId + '\delivery-index.json')
        if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) { throw 'Build did not produce a verified index; stopped even if the builder returned exit code 0.' }
        $index = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (@($index.targets).Count -ne $Targets.Count) { throw 'Verified index is missing a requested target.' }
    }
} finally { $env:CSC_IDENTITY_AUTO_DISCOVERY = $oldDiscovery }
