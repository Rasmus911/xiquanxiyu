[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DeliveryRoot,
    [ValidateSet('build','publish','all','validate')][string]$Mode = 'all',
    [string]$EcsTarget = 'root@39.96.217.210',
    [string]$PreviousApkPath
)
$ErrorActionPreference='Stop'
$project=Split-Path -Parent $PSScriptRoot
$delivery=(Resolve-Path -LiteralPath $DeliveryRoot).Path
$info=Get-Content -LiteralPath (Join-Path $delivery '交付信息.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($info.Version -cne '0.5.6' -or $info.MobileVersion -cne '1.2.13' -or $info.MobileVersionCode -ne 20) { throw 'Unreviewed release identity.' }
if ($EcsTarget -notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$') { throw 'Invalid SSH target.' }
& node.exe (Join-Path $PSScriptRoot 'lib\desktop-056.cjs') verify-delivery $delivery
if ($LASTEXITCODE -ne 0) { throw 'Frozen delivery differs. No build or upload.' }
if($Mode-in @('all','publish')){
    & node.exe (Join-Path $PSScriptRoot 'lib\desktop-056-source.cjs') completed $delivery
    if($LASTEXITCODE-ne 0){throw 'Complete the exact 0.5.6 cloud deployment before activating Android feeds.'}
}
if (-not $PreviousApkPath) { $PreviousApkPath=Join-Path $project 'release\mobile\xiquan-mobile-ordering-1.2.12.apk' }
if (-not (Test-Path -LiteralPath $PreviousApkPath -PathType Leaf)) { throw 'Keep the original 1.2.12 certificate reference APK; never uninstall to bypass signing.' }
$version=Get-Content -LiteralPath (Join-Path $project 'mobile\version.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($version.version -cne '1.2.13' -or $version.versionCode -ne 20 -or $version.minimumVersionCode -ne 9) { throw 'Mobile source identity differs.' }
if ($Mode -eq 'validate') {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build-mobile-release.ps1') -Version '1.2.13' -VersionCode 20 -MinimumVersionCode 9 -ValidateOnly
    if ($LASTEXITCODE -ne 0) { throw 'Android tool validation failed.' }
    Write-Host 'LOCAL_ONLY_OK: no password, signing, SSH or cloud changes.'
    return
}
if ($Mode -in @('build','all')) {
    $oldBuild=$env:VITE_BUILD_ID; $oldApi=$env:VITE_API_BASE_URL
    try {
        $env:VITE_BUILD_ID=$info.BuildId; $env:VITE_API_BASE_URL='https://api.pqxqxy.xyz/api'
        $buildParameters=@{
            Version='1.2.13'
            VersionCode=20
            MinimumVersionCode=9
            ReleaseNotes=('给桌面端的图标做出更换'+"`n"+'优化“库存”页面布局')
        }
        & (Join-Path $PSScriptRoot 'build-mobile-release.ps1') @buildParameters
        if ($LASTEXITCODE -ne 0) { throw 'Android build stopped. No upload.' }
    } finally { $env:VITE_BUILD_ID=$oldBuild; $env:VITE_API_BASE_URL=$oldApi }
}
. (Join-Path $PSScriptRoot 'lib\mobile-release-signature.ps1')
$apk=Join-Path $project 'release\mobile\xiquan-mobile-ordering-1.2.13.apk'
$signed=Assert-SignedMobileRelease -ApkPath $apk -PreviousApkPath $PreviousApkPath -ExpectedVersion '1.2.13' -ExpectedVersionCode 20
if ($signed.CertificateSha256 -cne '15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9') { throw 'Original Android signer mismatch.' }
$configPath=Join-Path $project 'deploy\cloud\mobile\download-config.json'
$config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$hash=(Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant()
if ($config.version -cne '1.2.13' -or $config.versionCode -ne 20 -or $config.sha256 -cne $hash -or $config.minimumVersionCode -ne 9) { throw 'APK and download configuration differ.' }
Copy-Item -LiteralPath $apk -Destination $delivery -Force
if ($Mode -eq 'build') { Write-Host 'Original-signed APK created. Nothing uploaded.'; return }
if ((Read-Host 'Only mobile static files and the Android feed change. Type PUBLISH ANDROID 1.2.13') -cne 'PUBLISH ANDROID 1.2.13') { throw 'Cancelled.' }
. (Join-Path $PSScriptRoot 'lib\desktop-053-transport.ps1')
$options=@('-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ConnectionAttempts=1','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
$remote='/tmp/xiquan-android128-'+[guid]::NewGuid().ToString('N')
$result=Invoke-TokenNative -Executable 'ssh.exe' -Arguments ($options+@($EcsTarget,('umask 077 && mkdir -m 700 '+$remote))) -TimeoutSeconds 45 -Label 'MOBILE1213 staging'
if ($result.ExitCode -ne 0) { throw ('SSH staging failed: '+$result.Stderr) }
function Send-File([string]$Local,[string]$Name) {
    $destination=$remote+'/'+$Name
    Write-Host ('UPLOAD_AND_SHA256: '+$Name)
    $program=New-TokenUploadProgram -LocalPath $Local -RemotePath $destination
    $result=Invoke-TokenNative -Executable 'ssh.exe' -Arguments ($options+@($EcsTarget,'python3 -')) -InputText ($program+"`n") -TimeoutSeconds 600 -Label ('MOBILE1213 '+$Name)
    $expected=(Get-FileHash -LiteralPath $Local -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($result.ExitCode -ne 0 -or $result.Stdout -notmatch ('(?m)^UPLOAD_VERIFIED '+$expected+' '+[regex]::Escape($destination)+'\r?$')) { throw ('Upload not verified. No activation. Retain '+$remote) }
    Write-Host ('FILE_VERIFIED: '+$Name)
}
$temporary=Join-Path $project ('release\mobile-staging\mobile1213-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary -Force | Out-Null
$webZip=Join-Path $temporary 'web.zip'
$web=Join-Path $project 'deploy\cloud\mobile'
$inputs=@('index.html','icon.svg','download-qr.svg','manifest.webmanifest','sw.js','assets') | ForEach-Object { Join-Path $web $_ }
Compress-Archive -LiteralPath $inputs -DestinationPath $webZip
Send-File (Join-Path $project 'deploy\cloud\scripts\android_1213_publication.py') 'publish.py'
Send-File $configPath 'config.json'
Send-File $apk 'app.apk'
Send-File $webZip 'web.zip'
$command='python3 -u '+$remote+'/publish.py --config '+$remote+'/config.json --apk '+$remote+'/app.apk --web-zip '+$remote+'/web.zip'
$result=Invoke-TokenNative -Executable 'ssh.exe' -Arguments ($options+@($EcsTarget,$command)) -TimeoutSeconds 180 -Label 'MOBILE1213 activation'
Write-Host $result.Stdout
if ($result.ExitCode -ne 0) { Write-Host $result.Stderr; throw ('Activation stopped. Retain '+$remote+' and publication backup; no API/database restore.') }
& node.exe (Join-Path $PSScriptRoot 'lib\mobile-1213-public.cjs') $apk
if ($LASTEXITCODE -ne 0) { throw 'Public verification incomplete. Keep the original-signed APK; do not rebuild/re-sign or redeploy the API.' }
Write-Host 'ANDROID1213_PUBLICATION_VERIFIED: old APP can download inside the application and confirm a covering install.'

