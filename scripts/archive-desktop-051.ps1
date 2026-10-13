[CmdletBinding()]
param([ValidateSet('plan','prepare','batch','verify','clean')][string]$Mode='plan')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path -Parent $PSScriptRoot
$clone=Join-Path $root 'private\溪泉版本仓库\xiquanxiyu'
$reports=Join-Path $root 'private\desktop051-archive'
[void](New-Item -ItemType Directory -Force -Path $reports)
$helper=Join-Path $PSScriptRoot 'lib\archive-plan-051.cjs'
$plan=Join-Path $reports 'plan.json';$prepared=Join-Path $reports 'prepared.json';$proof=Join-Path $reports 'remote-proof.json'
if($Mode-eq 'batch'){
    & node.exe $helper batch $root $clone $prepared (Join-Path $reports 'batch-status.json')
    if($LASTEXITCODE-ne 0){throw 'Batch stopped; originals and private queue retained.'}
    return
}
if($Mode-eq 'plan' -or $Mode-eq 'prepare'){
    & node.exe $helper plan $root $clone '-' $plan
    if($LASTEXITCODE-ne 0){throw 'Read-only archive plan failed.'}
    if($Mode-eq 'plan'){return}
    & node.exe $helper prepare $root $clone $plan $prepared
    if($LASTEXITCODE-ne 0){throw 'Archive preparation stopped; originals retained.'}
    Write-Host 'Prepared only. Use the requested GitHub Desktop to inspect, Commit and Push origin; not uploaded yet.'
    return
}
& node.exe $helper verify $root $clone $prepared $proof
if($LASTEXITCODE-ne 0){throw 'Remote byte proof failed; no local cleanup.'}
if($Mode-eq 'verify'){return}
$latest=Join-Path $root '最新版安装包-实体卡消费-0.5.1'
& node.exe (Join-Path $PSScriptRoot 'lib\desktop-051.cjs') verify-delivery $latest
if($LASTEXITCODE-ne 0){throw 'Current delivery invalid; no cleanup.'}
& node.exe $helper eligible $root $clone $proof '-'
if($LASTEXITCODE-ne 0){throw 'Exact fresh proof invalid; no cleanup.'}
$verified=Get-Content -LiteralPath $proof -Raw -Encoding UTF8|ConvertFrom-Json
$removed=@()
foreach($entry in $verified.entries){
    $file=[IO.Path]::GetFullPath((Join-Path $root $entry.path))
    if(-not $file.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Cleanup escaped exact root.'}
    $item=Get-Item -LiteralPath $file -Force
    if($item.PSIsContainer -or $item.Length-ne $entry.size){throw 'Cleanup leaf changed.'}
    $cursor=$item
    while($cursor.FullName-ne $root){
        if($cursor.Attributes-band [IO.FileAttributes]::ReparsePoint){throw 'Linked cleanup ancestor refused.'}
        $cursor=if($cursor.PSIsContainer){$cursor.Parent}else{$cursor.Directory}
    }
    $stream=[IO.File]::OpenRead($file);$sha=[Security.Cryptography.SHA256]::Create()
    try{$actual=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}finally{$stream.Dispose();$sha.Dispose()}
    if($actual-cne $entry.sha256){throw 'Cleanup hash changed.'}
    Remove-Item -LiteralPath $file -Force
    $removed+=$entry
    # Incremental receipt survives interruption; no recursive deletion.
    [IO.File]::WriteAllText((Join-Path $reports 'cleanup-receipt.json'),([ordered]@{RemoteCommit=$verified.remoteCommit;Removed=$removed;Recoverable=$true}|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
}
$directories=@($verified.entries|ForEach-Object{[IO.Path]::GetDirectoryName((Join-Path $root $_.path))}|Sort-Object -Unique)
foreach($directory in $directories|Sort-Object Length -Descending){
    $current=$directory
    while($current -and $current-ne $root -and $current.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){
        if(-not(Test-Path -LiteralPath $current)){break}
        $item=Get-Item -LiteralPath $current -Force
        if(($item.Attributes-band [IO.FileAttributes]::ReparsePoint)-or @(Get-ChildItem -LiteralPath $current -Force).Count){break}
        $next=[IO.Path]::GetDirectoryName($current)
        Remove-Item -LiteralPath $current
        $current=$next
    }
}
Write-Host ('Removed proven historical leaf files: '+$removed.Count+'; recover from remote commit '+$verified.remoteCommit)
