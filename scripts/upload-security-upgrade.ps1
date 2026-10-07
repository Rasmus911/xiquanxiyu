[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BundlePath,
    [string]$EcsTarget = 'root@39.96.217.210',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($EcsTarget -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$') { throw 'EcsTarget must be user@host with no extra SSH arguments.' }
. (Join-Path $PSScriptRoot 'lib\security-release-bundle.ps1')
. (Join-Path $PSScriptRoot 'lib\mobile-release-signature.ps1')
$release = Assert-SecurityReleaseBundle -Path $BundlePath
$zipHash = (Get-FileHash -LiteralPath $release.Path -Algorithm SHA256).Hash.ToLowerInvariant()
$remoteScriptPath = Join-Path $PSScriptRoot 'deploy-security-upgrade.sh'
if (-not (Test-Path -LiteralPath $remoteScriptPath -PathType Leaf)) { throw 'Deployment script is missing.' }
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$previousApk = Join-Path $projectRoot 'release\mobile\xiquan-mobile-ordering-1.1.1.apk'
if (-not (Test-Path -LiteralPath $previousApk -PathType Leaf) -or
    (Get-FileHash -LiteralPath $previousApk -Algorithm SHA256).Hash.ToLowerInvariant() -ne '72312dac652a0ddff06f036e946724f8e93680ece3cccc08e827d1bd69d78432') {
    throw 'Original 1.1.1 APK signature reference is missing or changed. Restore the trusted original file; do not replace it with a newly signed APK.'
}
$apkCheckRoot = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-apk-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $apkCheckRoot | Out-Null
try {
    $archive = [IO.Compression.ZipFile]::OpenRead($release.Path)
    try {
        $apkEntry = @($archive.Entries | Where-Object { $_.FullName.Replace('\', '/') -eq 'xiquan/deploy/cloud/mobile/downloads/xiquan-mobile-ordering-1.2.0.apk' })[0]
        $apkCheckPath = Join-Path $apkCheckRoot 'release.apk'
        [IO.Compression.ZipFileExtensions]::ExtractToFile($apkEntry, $apkCheckPath)
    }
    finally { $archive.Dispose() }
    $signature = Assert-SignedMobileRelease -ApkPath $apkCheckPath -PreviousApkPath $previousApk
    Write-Host "Verified actual Android 1.2.0/code 7 and original signer: $($signature.CertificateSha256)"
}
finally {
    $resolvedCheckRoot = [IO.Path]::GetFullPath($apkCheckRoot)
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedCheckRoot.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing APK check cleanup outside TEMP.' }
    Remove-Item -LiteralPath $resolvedCheckRoot -Recurse -Force
}
Write-Host "Validated: desktop $($release.DesktopVersion), Android $($release.MobileVersion), web $($release.WebBuildId)"
Write-Host "ZIP: $($release.Path)"
Write-Host "SHA256: $zipHash"
if ($ValidateOnly) {
    Write-Host 'Local validation only. No SSH, upload, cloud or database changes.' -ForegroundColor Green
    return
}

foreach ($command in @('ssh.exe', 'scp.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Required command missing: $command" }
}
Write-Warning 'Production migration requires prior acceptance on an isolated PostgreSQL 17 test database.'
Write-Warning 'Stop business writes on ALL computers and phones before deployment. Everyone must log in again.'
Write-Warning 'Backups include private .env and business data. They remain on ECS in a private directory; keep a separate secure copy.'
Write-Warning 'This desktop installer is not Windows publisher-signed. Read the security release guide before external distribution.'
$confirmation = Read-Host 'After test acceptance and stopping business writes, type DEPLOY to upload and migrate ECS'
if ($confirmation -cne 'DEPLOY') { throw 'Deployment cancelled before any SSH or upload.' }

$ecsHost = $EcsTarget.Split('@')[1]
if (-not (Test-NetConnection -ComputerName $ecsHost -Port 22 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
    throw 'ECS port 22 is unreachable. Check security group/source IP, proxy and SSH service. Nothing was uploaded.'
}
$connectionOptions = @('-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3')
# Keep normal SSH host-key checks; never disable StrictHostKeyChecking.
& ssh.exe -T @connectionOptions $EcsTarget "test -f /opt/xiquan/xiquan/deploy/cloud/.env && command -v docker >/dev/null && command -v python3 >/dev/null && test ! -L /opt/xiquan-releases && install -d -m 0700 /opt/xiquan-releases"
if ($LASTEXITCODE -ne 0) { throw 'SSH/server preflight failed. Running services were not changed.' }
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$remoteZip = "/opt/xiquan-releases/$runId.zip"
& scp.exe @connectionOptions $release.Path "${EcsTarget}:$remoteZip"
if ($LASTEXITCODE -ne 0) { throw 'Upload failed; running services were not changed. Do not run a migration separately.' }

$remoteScript = "/opt/xiquan-releases/$runId.sh"
$scriptHash = (Get-FileHash -LiteralPath $remoteScriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
& scp.exe @connectionOptions $remoteScriptPath "${EcsTarget}:$remoteScript"
if ($LASTEXITCODE -ne 0) { throw 'Deployment script upload failed; running services were not changed.' }
# Verify exact bytes first, normalize CRLF on ECS, then execute a file with closed stdin.
# Never pipe Bash source through Windows PowerShell: it can append an extra CRLF.
& ssh.exe -T @connectionOptions $EcsTarget "printf '%s  %s\n' '$scriptHash' '$remoteScript' | sha256sum --check --status && sed -i 's/\r$//' '$remoteScript' && chmod 0600 '$remoteScript' && bash '$remoteScript' '$remoteZip' '$zipHash' '$runId' </dev/null"
if ($LASTEXITCODE -ne 0) {
    throw "ECS deployment did not complete. Preserve /opt/xiquan-backups/release-$runId and inspect logs. Do not blindly roll back or reinstall."
}

$health = Invoke-RestMethod -Uri 'https://api.pqxqxy.xyz/api/health' -TimeoutSec 30
if (-not $health.success -or $health.data.database -ne 'ok') { throw 'Public API/database health check failed from this computer.' }
$policy = Invoke-RestMethod -Uri 'https://api.pqxqxy.xyz/releases/client-policy.json' -TimeoutSec 30
if ($policy.desktop.sha256 -ne $release.DesktopSha256 -or $policy.android.sha256 -ne $release.MobileSha256) {
    throw 'Public installer hashes do not match the release uploaded from this computer.'
}
Write-Host 'Upload and deployment checks completed. Run cashier/phone/printing acceptance before resuming business.' -ForegroundColor Green
Write-Host "Backup: /opt/xiquan-backups/release-$runId"
Write-Host 'Desktop: https://api.pqxqxy.xyz/updates/Xiquan-Bathhouse-Setup-0.4.0.exe'
Write-Host 'Mobile: https://api.pqxqxy.xyz/mobile/download'
