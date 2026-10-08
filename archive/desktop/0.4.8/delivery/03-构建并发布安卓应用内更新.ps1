[CmdletBinding()]
param([string]$EcsTarget='root@39.96.217.210',[string]$PreviousApkPath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$delivery=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$root=$delivery.ProjectRoot
function Assert-ReviewedSource([switch]$AfterBuild) {
    $arguments=@((Join-Path $root 'scripts\lib\reviewed-source.cjs'),$root,$delivery.SourceCommit)
    if($AfterBuild){$arguments+='after-android'}
    & node.exe @arguments
    if($LASTEXITCODE-ne 0){throw 'Local source differs from delivered/reviewed commit. Stopped before signing or upload.'}
}
Assert-ReviewedSource
if($EcsTarget-notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$'){throw 'Invalid SSH target.'}
if((Read-Host 'Confirm cloud 0.4.8 succeeded. Type PUBLISH ANDROID 1.2.6')-cne 'PUBLISH ANDROID 1.2.6'){throw 'Cancelled.'}
if(-not $PreviousApkPath){
    foreach($version in @('1.2.5','1.2.4','1.2.3','1.2.2')){
        $candidate=Join-Path $root ('release\mobile\xiquan-mobile-ordering-'+$version+'.apk')
        if(Test-Path -LiteralPath $candidate -PathType Leaf){$PreviousApkPath=$candidate;break}
    }
}
if(-not $PreviousApkPath){throw 'Previous original-signed APK required; pass -PreviousApkPath. Do not create a new certificate or uninstall.'}
Push-Location -LiteralPath $root
try {
    $oldBuild=$env:VITE_BUILD_ID; $oldApi=$env:VITE_API_BASE_URL
    try {
        $env:VITE_BUILD_ID=$delivery.SourceCommit; $env:VITE_API_BASE_URL='https://api.pqxqxy.xyz/api'
        $notes=@('1. 澡巾、备品、搓泥宝改为服务项目','2. 加单后弹窗选择耗材','3. 库存和项目商品每页10项，右上角翻页','4. 库存显示和编辑成本单价，已设置成本修改需本人密码') -join "`n"
        & (Join-Path $root 'scripts\build-mobile-release.ps1') -Version '1.2.6' -VersionCode 13 -MinimumVersionCode 9 -ReleaseNotes $notes
    } finally {$env:VITE_BUILD_ID=$oldBuild;$env:VITE_API_BASE_URL=$oldApi}
    Assert-ReviewedSource -AfterBuild
    . (Join-Path $root 'scripts\lib\mobile-release-signature.ps1')
    $apk=Join-Path $root 'release\mobile\xiquan-mobile-ordering-1.2.6.apk'
    $identity=Assert-SignedMobileRelease -ApkPath $apk -PreviousApkPath $PreviousApkPath -ExpectedVersion '1.2.6' -ExpectedVersionCode 13
    if($identity.CertificateSha256-cne '15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9'){throw 'Original Android signer mismatch. No upload.'}
    $config=Join-Path $root 'deploy\cloud\mobile\download-config.json'
    $publisher=Join-Path $root 'deploy\cloud\scripts\android_126_publication.py'
    $options=@('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
    $remote='/tmp/xiquan-android126-'+[guid]::NewGuid().ToString('N')
    & ssh.exe @options $EcsTarget ('umask 077 && mkdir -m 700 '+$remote)
    if($LASTEXITCODE-ne 0){throw 'Private staging failed.'}
    $inputs=@(@{File=$publisher;Name='publish.py'},@{File=$config;Name='config.json'},@{File=$apk;Name='app.apk'})
    foreach($inputFile in $inputs){
        & scp.exe @options -- $inputFile.File ($EcsTarget+':'+$remote+'/'+$inputFile.Name)
        if($LASTEXITCODE-ne 0){throw 'Android upload failed. Existing feeds unchanged.'}
        $expected=(Get-FileHash -LiteralPath $inputFile.File -Algorithm SHA256).Hash.ToLowerInvariant()
        $actual=& ssh.exe @options $EcsTarget ('sha256sum '+$remote+'/'+$inputFile.Name)
        if($LASTEXITCODE-ne 0 -or @($actual).Count-ne 1 -or $actual-notmatch ('^'+$expected+'\s')){throw 'Remote Android input hash mismatch.'}
    }
    & ssh.exe @options $EcsTarget ('python3 '+$remote+'/publish.py --config '+$remote+'/config.json --apk '+$remote+'/app.apk')
    if($LASTEXITCODE-ne 0){throw ('Android publication stopped; preserve private staging '+$remote)}
    $public=Invoke-RestMethod -Uri 'https://api.pqxqxy.xyz/releases/client-policy.json' -TimeoutSec 30
    $expectedApk=(Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant()
    if($public.android.latestVersionCode-ne 13 -or $public.android.sha256-cne $expectedApk){throw 'Public Android policy differs; preserve output.'}
    Copy-Item -LiteralPath $apk -Destination (Join-Path $PSScriptRoot 'xiquan-mobile-ordering-1.2.6.apk') -Force
    Write-Host 'Android in-app update published. Open the old APP and check updates; no uninstall or webpage download needed.'
} finally {Pop-Location}
