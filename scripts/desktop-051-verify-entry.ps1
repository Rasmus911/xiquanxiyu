[CmdletBinding()]
param([string]$EcsTarget='root@39.96.217.210',[switch]$CheckPublished)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$delivery=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
& node.exe (Join-Path $delivery.ProjectRoot 'scripts\lib\desktop-051.cjs') verify-delivery $PSScriptRoot
if($LASTEXITCODE-ne 0){throw 'Delivery hashes changed.'}
if($EcsTarget-notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$'){throw 'Invalid SSH target.'}
$receipt=Get-Content -LiteralPath (Join-Path $PSScriptRoot '云端部署结果.json') -Raw -Encoding UTF8|ConvertFrom-Json
if($receipt.Job-notmatch '^/opt/xiquan-backups/desktop051-cutover-[a-f0-9]{32}$'){throw 'Exact completed deployment job required.'}
. (Join-Path $delivery.ProjectRoot 'scripts\lib\mobile-128-transport.ps1')
$options=@('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
$file=Join-Path $delivery.ProjectRoot 'deploy\cloud\scripts\desktop_051_completion.py'
$stream=[IO.File]::OpenRead($file);$sha=[Security.Cryptography.SHA256]::Create()
try{$hash=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}finally{$stream.Dispose();$sha.Dispose()}
if($hash-cne $delivery.CompletionToolSha256){throw 'Reviewed completion tool changed.'}
$remote='/tmp/xiquan-completion051-'+[guid]::NewGuid().ToString('N')+'.py'
$upload=Invoke-TokenNative -Executable 'scp.exe' -Arguments @($options+@('--',$file,($EcsTarget+':'+$remote))) -TimeoutSeconds 120 -Label 'COMPLETION upload'
if($upload.ExitCode-ne 0){throw 'Completion upload failed.'}
$command='test "$(sha256sum '+$remote+' | cut -d" " -f1)" = '+$hash+' && python3 '+$remote+' --job '+$receipt.Job+' --commit '+$delivery.SourceCommit+' --sha256 '+$delivery.SourceSha256
$check=Invoke-TokenNative -Executable 'ssh.exe' -Arguments @($options+@($EcsTarget,$command)) -TimeoutSeconds 240 -Label 'READ ONLY exact completed check'
if($check.ExitCode-ne 0){throw 'Exact completion/health check failed; no publication.'}
$checked=$check.Stdout|ConvertFrom-Json
if(-not $checked.completed -or $checked.source_commit-cne $delivery.SourceCommit){throw 'Completed identity differs.'}
if($CheckPublished){
    & node.exe (Join-Path $delivery.ProjectRoot 'scripts\lib\windows-public-check.cjs') $delivery.ReleaseRoot ($delivery.Targets-join ',')
    if($LASTEXITCODE-ne 0){throw 'Published signed channel bytes differ.'}
}
$checked
