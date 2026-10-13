[CmdletBinding()]
param(
    [ValidateSet('api','build','publish','all','validate')][string]$Mode = 'build',
    [Parameter(Mandatory = $true)][string]$DeliveryInfoPath,
    [string]$EcsTarget = 'root@39.96.217.210',
    [string]$PreviousApkPath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$delivery = Get-Content -LiteralPath $DeliveryInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
$root = $delivery.ProjectRoot
$folder = Split-Path -Parent $DeliveryInfoPath
$releaseVersion = if ($delivery.PSObject.Properties['Version']) { [string]$delivery.Version } else { '1.2.8' }
$releaseCode = if ($delivery.PSObject.Properties['VersionCode']) { [int]$delivery.VersionCode } else { 15 }
if (-not (($releaseVersion -ceq '1.2.8' -and $releaseCode -eq 15) -or
          ($releaseVersion -ceq '1.2.9' -and $releaseCode -eq 16))) { throw 'Unreviewed Android release identity.' }
if ($EcsTarget -notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$') { throw 'Invalid SSH target.' }
if (-not $PreviousApkPath) {
    $previousVersion = if ($releaseVersion -ceq '1.2.9') { '1.2.8' } else { '1.2.7' }
    $PreviousApkPath = Join-Path $root ('release\mobile\xiquan-mobile-ordering-' + $previousVersion + '.apk')
}
$options = @('-o','BatchMode=yes','-o','ConnectionAttempts=1','-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
. (Join-Path $root 'scripts\lib\mobile-128-transport.ps1')

function Assert-Source([switch]$AfterBuild) {
    $arguments = @((Join-Path $root 'scripts\lib\reviewed-source.cjs'), $root, $delivery.SourceCommit)
    if ($AfterBuild) { $arguments += 'after-android' }
    & node.exe @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Delivered source changed. Stop before signing or upload.' }
}

function Invoke-Ssh {
    param([string]$Command, [string]$Label = 'PREPARE_PRIVATE_STAGE', [switch]$Live)
    Write-Host ('TOKEN_PHASE=' + $Label)
    if ($Live) {
        # Do not kill a deployment command mid-cutover. Its reviewed Python
        # helper bounds each command and prints its private recovery evidence.
        & ssh.exe -T @options $EcsTarget $Command
        if ($LASTEXITCODE -ne 0) { throw 'Cloud command failed. Retain output and private evidence. Do not rerun old deployment scripts.' }
    } else {
        $result = Invoke-TokenNative -Executable 'ssh.exe' -Arguments (@('-T') + $options + @($EcsTarget, $Command)) `
            -TimeoutSeconds 45 -Label $Label
        if ($result.ExitCode -ne 0) { throw ('SSH stopped: ' + $result.Stderr.Trim()) }
        if ($result.Stdout) { Write-Host $result.Stdout.Trim() }
    }
}

function Send-VerifiedFile([string]$Local, [string]$Remote) {
    $name = [IO.Path]::GetFileName($Local)
    Write-Host ('TOKEN_PHASE=UPLOAD_AND_VERIFY ' + $name)
    $program = New-TokenUploadProgram -LocalPath $Local -RemotePath $Remote
    $deadline = if ((Get-Item -LiteralPath $Local).Length -gt 1MB) { 300 } else { 90 }
    $result = Invoke-TokenNative -Executable 'ssh.exe' -Arguments (@('-T') + $options + @($EcsTarget, 'python3 -')) `
        -InputText ($program + "`n") -TimeoutSeconds $deadline -Label ('UPLOAD ' + $name)
    if ($result.ExitCode -ne 0) { throw ('Upload stopped: ' + $result.Stderr.Trim() + '. Staging retained: ' + $Remote) }
    $expected = (Get-FileHash -LiteralPath $Local -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($result.Stdout -notmatch ('(?m)^UPLOAD_VERIFIED ' + $expected + ' ' + [regex]::Escape($Remote) + '\r?$')) {
        throw 'Remote input checksum mismatch. Publication stopped.'
    }
    Write-Host ('TOKEN_PHASE=FILE_VERIFIED ' + $name)
}

function Update-Api {
    Assert-Source
    $source = Join-Path $root 'server\app\api\mobile.py'
    $digest = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($digest -cne '31889af111c17074a4cbb49ed1f610fa6338efea46e4698a87cdf91b71d4724b') {
        throw 'API patch differs from reviewed bytes. Nothing uploaded.'
    }
    if ((Read-Host 'Short API restart, no database changes. Type UPDATE TOKEN') -cne 'UPDATE TOKEN') { throw 'Cancelled.' }
    $remote = '/tmp/xiquan-token128-' + [guid]::NewGuid().ToString('N')
    Write-Host ('TOKEN_STAGING=' + $remote)
    Invoke-Ssh ('umask 077 && mkdir -m 700 ' + $remote)
    Send-VerifiedFile (Join-Path $root 'deploy\cloud\scripts\registration_token128_patch.py') ($remote + '/patch.py')
    Send-VerifiedFile $source ($remote + '/mobile.py')
    Invoke-Ssh -Command ('python3 -u ' + $remote + '/patch.py --source ' + $remote + '/mobile.py --sha256 ' + $digest) `
        -Label 'EXECUTE_VERIFIED_API_PATCH' -Live
    Write-Host 'Narrow API patch returned successfully. Keep its PRIVATE_TOKEN_PATCH_JOB output.'
}

function Build-App {
    Assert-Source
    $oldBuild = $env:VITE_BUILD_ID; $oldApi = $env:VITE_API_BASE_URL
    try {
        $env:VITE_BUILD_ID = $delivery.SourceCommit
        $env:VITE_API_BASE_URL = 'https://api.pqxqxy.xyz/api'
        $notes = if ($releaseVersion -ceq '1.2.9') { '修复应用内更新无法打开系统安装器' } else {
            @('手机底部新增“注册令牌”入口','修复数据同步后注册令牌入口消失') -join "`n"
        }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\build-mobile-release.ps1') `
            -Version $releaseVersion -VersionCode $releaseCode -MinimumVersionCode 9 -ReleaseNotes $notes
        if ($LASTEXITCODE -ne 0) { throw 'Android build failed. No publication performed.' }
    } finally { $env:VITE_BUILD_ID = $oldBuild; $env:VITE_API_BASE_URL = $oldApi }
    Assert-Source -AfterBuild
    Assert-App
    Copy-Item -LiteralPath (Join-Path $root ('release\mobile\xiquan-mobile-ordering-' + $releaseVersion + '.apk')) -Destination $folder -Force
    Write-Host ('Original-signed APK verified. No upload: ' + (Join-Path $folder ('xiquan-mobile-ordering-' + $releaseVersion + '.apk')))
}

function Assert-App {
    . (Join-Path $root 'scripts\lib\mobile-release-signature.ps1')
    $apk = Join-Path $root ('release\mobile\xiquan-mobile-ordering-' + $releaseVersion + '.apk')
    $identity = Assert-SignedMobileRelease -ApkPath $apk -PreviousApkPath $PreviousApkPath -ExpectedVersion $releaseVersion -ExpectedVersionCode $releaseCode
    if ($identity.CertificateSha256 -cne '15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9') {
        throw 'Original Android certificate mismatch. No upload.'
    }
    $config = Get-Content -LiteralPath (Join-Path $root 'deploy\cloud\mobile\download-config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $digest = (Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($config.version -cne $releaseVersion -or $config.versionCode -ne $releaseCode -or $config.minimumVersionCode -ne 9 -or
        $config.sha256 -cne $digest -or $config.androidApkUrl -cne ('/mobile/downloads/xiquan-mobile-ordering-' + $releaseVersion + '.apk')) {
        throw 'Signed APK and download configuration differ. No upload.'
    }
}

function Publish-App {
    Assert-Source -AfterBuild
    Assert-App
    $publishConfirmation = 'PUBLISH ANDROID ' + $releaseVersion
    $publishPrompt = if ($releaseVersion -ceq '1.2.9') { 'Publish the Android installer fix. Type ' } else { 'Confirm API token patch succeeded. Type ' }
    if ((Read-Host ($publishPrompt + $publishConfirmation)) -cne $publishConfirmation) { throw 'Cancelled.' }
    # The preceding API patch must be active in the healthy running container.
    $verify = 'docker exec xiquan-api-1 sha256sum /app/app/api/mobile.py'
    Write-Host 'TOKEN_PHASE=VERIFY_RUNNING_API_PATCH'
    $verified = Invoke-TokenNative -Executable 'ssh.exe' -Arguments (@('-T') + $options + @($EcsTarget, $verify)) `
        -TimeoutSeconds 45 -Label 'VERIFY_RUNNING_API_PATCH'
    if ($verified.ExitCode -ne 0 -or $verified.Stdout.Trim() -notmatch '^31889af111c17074a4cbb49ed1f610fa6338efea46e4698a87cdf91b71d4724b\s') {
        throw 'Running API patch is not verified. Existing update feeds unchanged.'
    }
    $remote = '/tmp/xiquan-android128-' + [guid]::NewGuid().ToString('N')
    Invoke-Ssh ('umask 077 && mkdir -m 700 ' + $remote)
    Send-VerifiedFile (Join-Path $root 'deploy\cloud\scripts\android_128_publication.py') ($remote + '/publish.py')
    Send-VerifiedFile (Join-Path $root 'deploy\cloud\mobile\download-config.json') ($remote + '/config.json')
    Send-VerifiedFile (Join-Path $root ('release\mobile\xiquan-mobile-ordering-' + $releaseVersion + '.apk')) ($remote + '/app.apk')
    $web = Join-Path $root 'deploy\cloud\mobile'
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-mobile128-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    $webArchive = Join-Path $temporary 'web.zip'
    $webInputs = @('index.html','icon.svg','download-qr.svg','manifest.webmanifest','sw.js','assets') |
        ForEach-Object { Join-Path $web $_ }
    Compress-Archive -LiteralPath $webInputs -DestinationPath $webArchive
    Send-VerifiedFile $webArchive ($remote + '/web.zip')
    Invoke-Ssh -Command ('python3 -u ' + $remote + '/publish.py --config ' + $remote + '/config.json --apk ' + $remote + '/app.apk --web-zip ' + $remote + '/web.zip') `
        -Label 'PUBLISH_VERIFIED_ANDROID_UPDATE' -Live
    $public = Invoke-RestMethod -Uri 'https://api.pqxqxy.xyz/releases/client-policy.json' -TimeoutSec 30
    $digest = (Get-FileHash -LiteralPath (Join-Path $root ('release\mobile\xiquan-mobile-ordering-' + $releaseVersion + '.apk')) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($public.android.latestVersionCode -ne $releaseCode -or $public.android.sha256 -cne $digest) { throw 'Public Android policy verification failed. Preserve output.' }
    Write-Host ('Android ' + $releaseVersion + ' in-app update published. Original desktop/web feeds and old APKs retained.')
}

Push-Location -LiteralPath $root
try {
    switch ($Mode) {
        'validate' {
            Assert-Source
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\build-mobile-release.ps1') `
                -Version $releaseVersion -VersionCode $releaseCode -MinimumVersionCode 9 -ValidateOnly
            if ($LASTEXITCODE -ne 0) { throw 'Local tool validation failed.' }
            Write-Host 'Local validation only. No signing, upload, restart or cloud change.'
        }
        'api' { Update-Api }
        'build' { Build-App }
        'publish' { Publish-App }
        'all' { Update-Api; Build-App; Publish-App }
    }
} finally { Pop-Location }
