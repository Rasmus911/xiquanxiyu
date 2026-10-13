[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DeliveryRoot,
    [ValidateSet('all','sign','publish','verify')][string]$Mode = 'all',
    [string]$EcsTarget = 'root@39.96.217.210',
    [string]$PrivateKeyPath,
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
if ($EcsTarget -notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$') { throw 'Invalid SSH target.' }
$project = Split-Path -Parent $PSScriptRoot
$deliveryPath = (Resolve-Path -LiteralPath $DeliveryRoot).Path
$delivery = Get-Content -LiteralPath (Join-Path $deliveryPath '交付信息.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$helper = Join-Path $PSScriptRoot 'lib\desktop-055.cjs'
$node = (Get-Command node.exe -ErrorAction Stop).Source
$targets = @('win10-x86','win10-x64','win11-x86','win11-x64')
$releaseRoot = $delivery.ReleaseRoot
$previousEncoding = $OutputEncoding
try {
    $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    Write-Host '校验 0.5.5 安装包、原发布公钥及发布脚本……'
    & $node $helper verify-delivery $deliveryPath
    if ($LASTEXITCODE -ne 0) { throw 'Local delivery verification failed. No signing or upload.' }
    if ($PreflightOnly) {
        Write-Host 'PREFLIGHT_ONLY_OK：仅本地校验，没有联网、签名、上传或修改数据库。'
        return
    }
    if($Mode-in @('all','publish')){
        & $node (Join-Path $PSScriptRoot 'lib\desktop-055-source.cjs') completed $deliveryPath
        if($LASTEXITCODE-ne 0){throw 'Complete the exact 0.5.5 cloud deployment before changing Windows channels.'}
    }
    $stateText = & $node $helper status $releaseRoot
    if ($LASTEXITCODE -ne 0) { throw 'Release checkpoint invalid.' }
    $state = ($stateText -join "`n") | ConvertFrom-Json
    if ($Mode -in @('all','sign') -and @($state.unsignedTargets).Count -gt 0) {
        if (-not $PrivateKeyPath) { $PrivateKeyPath = Join-Path $project 'private\溪泉发布密钥\desktop-release-private.pem' }
        if (-not (Test-Path -LiteralPath $PrivateKeyPath -PathType Leaf)) { throw 'Original encrypted release key is missing; do not create a replacement key.' }
        Write-Host '读取并验签四个现行更新策略，结合本机历史原密钥签名计算递增发布序号……'
        $planText = & $node $helper plan $deliveryPath
        if ($LASTEXITCODE -ne 0) { throw 'Current signed policies unavailable. No guessed sequence; nothing uploaded.' }
        $plan = ($planText -join "`n") | ConvertFrom-Json
        $groupsText = $plan | ConvertTo-Json -Depth 12 -Compress | & $node $helper groups $releaseRoot
        if ($LASTEXITCODE -ne 0) { throw 'Existing signatures conflict with the verified plan; stopped.' }
        $groups = ($groupsText -join "`n") | ConvertFrom-Json
        foreach ($group in $groups) {
            Write-Host ('为以下通道签名：' + ($group.targets -join ', '))
            & (Join-Path $PSScriptRoot 'sign-windows-release.ps1') -ReleaseRoot $releaseRoot `
                -PrivateKeyPath $PrivateKeyPath -Sequence $plan.sequence -MinimumVersion $group.minimumVersion `
                -Targets @($group.targets) -ReleaseNotes @('取消下单“选择耗材”的步骤','可以通过导入外部Excel来整理库存')
        }
        $stateText = & $node $helper status $releaseRoot
        if ($LASTEXITCODE -ne 0) { throw 'Signed manifests did not pass validation.' }
        $state = ($stateText -join "`n") | ConvertFrom-Json
    }
    if ($Mode -eq 'sign') {
        if (@($state.unsignedTargets).Count -ne 0) { throw 'Signing incomplete.' }
        Write-Host 'DESKTOP055_SIGNED_LOCALLY：四通道签名校验通过，尚未上传。'
        return
    }
    if (@($state.unsignedTargets).Count -ne 0) { throw 'Publication requires all four original-key signatures.' }
    if ($Mode -in @('all','publish')) {
        if ((Read-Host '只发布桌面更新，不部署 API、不改数据库。输入 PUBLISH 0.5.5 继续') -cne 'PUBLISH 0.5.5') { throw 'Publication cancelled.' }
        $stage = Join-Path $project ('release\windows-staging\xiquan-windows-055-' + [guid]::NewGuid().ToString('N'))
        $policy = Join-Path $project 'deploy\cloud\releases\client-policy.json'
        & $node (Join-Path $PSScriptRoot 'lib\windows-publish.cjs') $releaseRoot $stage $policy '/opt/xiquan/xiquan/deploy/cloud' live ($targets -join ',')
        if ($LASTEXITCODE -ne 0) { throw 'Signed staging failed. No SSH/SCP was run.' }
        $remoteStage = '/tmp/' + (Split-Path -Leaf $stage)
        Write-Host ('LOCAL_SIGNED_STAGE=' + $stage)
        Write-Host ('REMOTE_SIGNED_STAGE=' + $remoteStage)
        . (Join-Path $PSScriptRoot 'lib\desktop-053-transport.ps1')
        $options = @('-o','ConnectTimeout=20','-o','ConnectionAttempts=1','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
        $uploadBytes=(Get-ChildItem -LiteralPath $stage -Recurse -File | Measure-Object -Property Length -Sum).Sum
        $uploadSeconds=[int][Math]::Min(7200,[Math]::Max(600,120+[Math]::Ceiling($uploadBytes/131072)))
        Write-Host ('UPLOAD_BYTES='+$uploadBytes+' TIMEOUT_SECONDS='+$uploadSeconds)
        $upload = Invoke-TokenNative -Executable 'scp.exe' -Arguments @($options + @('-r',$stage,($EcsTarget + ':/tmp/'))) -TimeoutSeconds $uploadSeconds -Label 'DESKTOP055 verified installers upload'
        Write-Host $upload.Stdout
        if ($upload.ExitCode -ne 0) { Write-Host $upload.Stderr; throw 'Upload failed. No channels were activated. Existing signatures retained.' }
        $activation = Invoke-TokenNative -Executable 'ssh.exe' -Arguments @($options + @($EcsTarget,('flock -w 60 /run/lock/xiquan-release-publication.lock bash ' + $remoteStage + '/activate.sh'))) -TimeoutSeconds 180 -Label 'DESKTOP055 channel activation'
        Write-Host $activation.Stdout
        if ($activation.ExitCode -ne 0) { Write-Host $activation.Stderr; throw 'Channel activation incomplete; preserve stage. Do not rerun API deployment.' }
        Write-Host 'DESKTOP055_CHANNELS_ACTIVATED：开始公开文件完整校验，下载进度会每 15 秒显示。'
    }
    # Unlike the old fixed five-minute check, this verifier budgets by file size,
    # reports progress, and only retries transient read-only transfers.
    & $node (Join-Path $PSScriptRoot 'lib\windows-public-recovery.cjs') $releaseRoot all
    if ($LASTEXITCODE -ne 0) {
        throw 'Public verification incomplete. Retain signed files; run the entry script with -Mode verify only. No re-signing, rebuild or database deployment.'
    }
    Write-Host 'DESKTOP055_PUBLICATION_VERIFIED：0.5.5 四通道及旧版过渡通道校验通过。旧软件现在可检查更新。'
} finally { $OutputEncoding = $previousEncoding }
