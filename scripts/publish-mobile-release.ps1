[CmdletBinding()]
param(
    [string]$EcsTarget = 'root@39.96.217.210',
    [string]$Version = '1.0.0',
    [string]$RemoteCloudDir = '/opt/xiquan/xiquan/deploy/cloud',
    [switch]$ValidateOnly,
    [switch]$StageOnly,
    [switch]$DryRun,
    [switch]$Required
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$mobileRoot = Join-Path $projectRoot 'mobile'
$deployMobileRoot = Join-Path $projectRoot 'deploy\cloud\mobile'
$apkName = "xiquan-mobile-ordering-$Version.apk"
$apkPath = Join-Path $deployMobileRoot "downloads\$apkName"
$configPath = Join-Path $deployMobileRoot 'download-config.json'
$indexPath = Join-Path $deployMobileRoot 'index.html'
$qrPath = Join-Path $deployMobileRoot 'download-qr.svg'
$httpsTemplate = Join-Path $projectRoot 'deploy\cloud\nginx\https.conf.template'
$httpTemplate = Join-Path $projectRoot 'deploy\cloud\nginx\http.conf.template'
$fixedDownloadUrl = 'https://api.pqxqxy.xyz/mobile/download'
$remoteMobileDir = "$RemoteCloudDir/mobile"
$remoteNginxDir = "$RemoteCloudDir/nginx"
$remoteArchive = "$RemoteMobileDir/mobile-web-$Version.tar.gz.new"
$remoteApkTemp = "$remoteMobileDir/downloads/$apkName.new"
$remoteConfigTemp = "$remoteMobileDir/download-config.json.$Version.new"
$policyPath = Join-Path $projectRoot 'deploy\cloud\releases\client-policy.json'
$policyHelper = Join-Path $projectRoot 'scripts\lib\release-policy.ps1'
. $policyHelper

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use x.y.z format: $Version"
}
if ($EcsTarget -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9.\[\]:_-]+$') {
    throw 'EcsTarget must look like root@1.2.3.4 or ubuntu@server.example.com.'
}
if ($RemoteCloudDir -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemoteCloudDir -match '/\.\.?(/|$)') {
    throw 'RemoteCloudDir must be a simple absolute Linux path.'
}

foreach ($command in @('node.exe', 'tar.exe', 'scp.exe', 'ssh.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}
foreach ($file in @($apkPath, $configPath, $indexPath, $qrPath, $httpsTemplate, $httpTemplate)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Required mobile release file not found: $file"
    }
}

$config = [System.IO.File]::ReadAllText($configPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$apkHash = (Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ([string]$config.version -ne $Version) { throw "Config version $($config.version) does not match $Version." }
if ([string]$config.androidApkUrl -ne "/mobile/downloads/$apkName") { throw 'Config APK URL does not match the release APK.' }
if ([string]$config.sha256 -ne $apkHash) { throw 'Config SHA256 does not match the release APK.' }
$policyRelease = @{
    latestVersion = $Version
    latestVersionCode = [int]$config.versionCode
    minimumVersionCode = [int]$config.minimumVersionCode
    required = [bool]$Required
    downloadUrl = "https://api.pqxqxy.xyz/mobile/downloads/$apkName"
    sha256 = $apkHash
    releaseNotes = @([string]$config.releaseNotes)
    publishedAt = [DateTimeOffset]::Now.ToString('o')
}

Push-Location $mobileRoot
try {
    $expectedQrLines = & node.exe -e "const QRCode=require('qrcode');QRCode.toString('$fixedDownloadUrl',{type:'svg',margin:2,width:420}).then(s=>process.stdout.write(s))"
    if ($LASTEXITCODE -ne 0) { throw 'Could not generate the expected QR code.' }
}
finally {
    Pop-Location
}
$expectedQr = (($expectedQrLines -join "`n") -replace "`r", '').Trim()
$actualQr = ([System.IO.File]::ReadAllText($qrPath, [System.Text.Encoding]::UTF8) -replace "`r", '').Trim()
if ($actualQr -ne $expectedQr) {
    throw "download-qr.svg does not encode the fixed URL: $fixedDownloadUrl"
}

$httpsText = [System.IO.File]::ReadAllText($httpsTemplate, [System.Text.Encoding]::UTF8)
$httpText = [System.IO.File]::ReadAllText($httpTemplate, [System.Text.Encoding]::UTF8)
foreach ($template in @($httpsText, $httpText)) {
    if ($template -notmatch 'location \^~ /mobile/downloads/' -or
        $template -notmatch 'application/vnd\.android\.package-archive') {
        throw 'An Nginx template is missing the Android APK static route.'
    }
}

Write-Host "Version: $Version"
Write-Host "APK: $apkPath"
Write-Host "SHA256: $apkHash"
Write-Host "QR URL: $fixedDownloadUrl"
if ($DryRun) {
    Write-Host 'Proposed policy:'
    Write-Host ($policyRelease | ConvertTo-Json -Depth 5)
    Write-Host 'Mobile release dry run passed.' -ForegroundColor Green
    exit 0
}
if ($ValidateOnly) {
    Write-Host 'Mobile release local validation passed.' -ForegroundColor Green
    exit 0
}
if ($StageOnly) {
    Update-ClientReleasePolicy -Path $policyPath -Platform android -Release $policyRelease
    Write-Host "Android $Version staged locally. No SSH connection or upload was made." -ForegroundColor Green
    exit 0
}

$archivePath = Join-Path $env:TEMP ("xiquan-mobile-web-$Version-" + [guid]::NewGuid().ToString('N') + '.tar.gz')
try {
    & tar.exe -czf $archivePath --exclude='./download-config.json' --exclude='./downloads' -C $deployMobileRoot .
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the mobile web archive.' }

    $prepareCommand = "install -d -m 0755 '$remoteMobileDir/downloads' '$remoteNginxDir'"
    & ssh.exe $EcsTarget $prepareCommand
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the remote mobile directories.' }

    & scp.exe $apkPath "${EcsTarget}:$remoteApkTemp"
    if ($LASTEXITCODE -ne 0) { throw 'APK upload failed.' }
    & scp.exe $archivePath "${EcsTarget}:$remoteArchive"
    if ($LASTEXITCODE -ne 0) { throw 'Mobile web archive upload failed.' }
    & scp.exe $httpsTemplate "${EcsTarget}:$remoteNginxDir/https.conf.template"
    if ($LASTEXITCODE -ne 0) { throw 'HTTPS Nginx template upload failed.' }
    & scp.exe $httpTemplate "${EcsTarget}:$remoteNginxDir/http.conf.template"
    if ($LASTEXITCODE -ne 0) { throw 'HTTP Nginx template upload failed.' }

    $stageCommand = @'
set -Eeuo pipefail
actual=$(sha256sum '__APK_TEMP__' | awk '{print $1}')
test "$actual" = '__APK_HASH__'
mv -f '__APK_TEMP__' '__APK_FINAL__'
tar -xzf '__WEB_ARCHIVE__' -C '__MOBILE_DIR__'
rm -f '__WEB_ARCHIVE__'
chmod 0644 '__APK_FINAL__'
'@
    $stageCommand = $stageCommand.Replace('__APK_TEMP__', $remoteApkTemp).
        Replace('__APK_HASH__', $apkHash).
        Replace('__APK_FINAL__', "$remoteMobileDir/downloads/$apkName").
        Replace('__WEB_ARCHIVE__', $remoteArchive).
        Replace('__MOBILE_DIR__', $remoteMobileDir)
    & ssh.exe $EcsTarget $stageCommand
    if ($LASTEXITCODE -ne 0) { throw 'Remote APK verification or web staging failed.' }

    & scp.exe $configPath "${EcsTarget}:$remoteConfigTemp"
    if ($LASTEXITCODE -ne 0) { throw 'Version config upload failed.' }

    $activateCommand = @'
set -Eeuo pipefail
cd '__CLOUD_DIR__'
set -a
. ./.env
set +a
cp nginx/active.conf nginx/active.conf.mobile-backup
sed "s/__API_DOMAIN__/${API_DOMAIN}/g" nginx/https.conf.template > nginx/active.conf.new
cat nginx/active.conf.new > nginx/active.conf
if ! docker compose --env-file .env -f docker-compose.prod.yml exec -T nginx nginx -t; then
    cat nginx/active.conf.mobile-backup > nginx/active.conf
    exit 1
fi
mv -f '__CONFIG_TEMP__' '__CONFIG_FINAL__'
chmod 0644 '__CONFIG_FINAL__'
docker compose --env-file .env -f docker-compose.prod.yml restart nginx
rm -f nginx/active.conf.new nginx/active.conf.mobile-backup
'@
    $activateCommand = $activateCommand.Replace('__CLOUD_DIR__', $RemoteCloudDir).
        Replace('__CONFIG_TEMP__', $remoteConfigTemp).
        Replace('__CONFIG_FINAL__', "$remoteMobileDir/download-config.json")
    & ssh.exe $EcsTarget $activateCommand
    if ($LASTEXITCODE -ne 0) { throw 'Could not activate the mobile release on ECS.' }
}
finally {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
}

$configUrl = 'https://api.pqxqxy.xyz/mobile/download-config.json'
$apkUrl = "https://api.pqxqxy.xyz/mobile/downloads/$apkName"
$publishedConfig = Invoke-RestMethod -Uri $configUrl -TimeoutSec 30
if ([string]$publishedConfig.version -ne $Version -or [string]$publishedConfig.sha256 -ne $apkHash) {
    throw 'Published version config does not match the local release.'
}
$downloadHead = Invoke-WebRequest -Uri $apkUrl -Method Head -UseBasicParsing -TimeoutSec 30
if ($downloadHead.StatusCode -ne 200) { throw "Published APK returned HTTP $($downloadHead.StatusCode)." }

Update-ClientReleasePolicy -Path $policyPath -Platform android -Release $policyRelease
$remoteReleaseDir = "$RemoteCloudDir/releases"
$remotePolicy = "$remoteReleaseDir/client-policy.json.$Version.new"
& ssh.exe $EcsTarget "install -d -m 0755 '$remoteReleaseDir'"
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the remote releases directory.' }
& scp.exe $policyPath "${EcsTarget}:$remotePolicy"
if ($LASTEXITCODE -ne 0) { throw 'Release policy upload failed.' }
& ssh.exe $EcsTarget "python3 -m json.tool '$remotePolicy' >/dev/null && mv -f '$remotePolicy' '$remoteReleaseDir/client-policy.json' && chmod 0644 '$remoteReleaseDir/client-policy.json'"
if ($LASTEXITCODE -ne 0) { throw 'Could not activate the release policy.' }
$publicPolicy = Invoke-RestMethod -Uri 'https://api.pqxqxy.xyz/releases/client-policy.json' -TimeoutSec 30
if ([string]$publicPolicy.android.latestVersion -ne $Version -or [string]$publicPolicy.android.sha256 -ne $apkHash) {
    throw 'Public release policy does not point to the new Android package.'
}

Write-Host "Mobile Android $Version published successfully." -ForegroundColor Green
Write-Host $fixedDownloadUrl
Write-Host $apkUrl
