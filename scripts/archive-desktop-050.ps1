[CmdletBinding()]
param(
    [ValidateSet('plan','prepare','verify','clean')][string]$Mode='plan',
    [string]$ArchiveClone,
    [string]$ReportDirectory
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=(Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
if(-not $ArchiveClone){$ArchiveClone=Join-Path $root 'private\溪泉版本仓库\xiquanxiyu'}
if(-not $ReportDirectory){$ReportDirectory=Join-Path $root 'private\desktop050-archive'}
$clone=(Resolve-Path -LiteralPath $ArchiveClone).Path
if($clone -ne (Join-Path $root 'private\溪泉版本仓库\xiquanxiyu')){throw 'Use the exact previously configured archive clone.'}
if(-not(Test-Path -LiteralPath $ReportDirectory)){[void](New-Item -ItemType Directory -Path $ReportDirectory)}
$helper=Join-Path $PSScriptRoot 'lib\archive-proof.cjs'
$plan=Join-Path $ReportDirectory 'plan.json'
$proof=Join-Path $ReportDirectory 'remote-proof.json'
& node.exe $helper plan $root $clone '-' $plan
if($LASTEXITCODE-ne 0){throw 'Read-only plan failed; no deletion.'}
if($Mode-eq 'plan'){Write-Host ('只读清单：'+$plan);return}
& node.exe $helper verify $root $clone $plan $proof
if($LASTEXITCODE-ne 0){throw 'Fresh remote verification failed; all local files retained.'}
if($Mode-eq 'verify'){Write-Host ('远端逐文件核实结果：'+$proof);return}
if($Mode-eq 'prepare'){
    & node.exe $helper prepare $root $clone $proof (Join-Path $ReportDirectory 'prepared.json')
    if($LASTEXITCODE-ne 0){throw 'Archive preparation stopped; local originals retained.'}
    Start-Process -FilePath 'C:\Users\lenovo\OneDrive\Desktop\GitHub Desktop.lnk' -WindowStyle Hidden
    Write-Host '归档副本已准备，尚未上传。请在 GitHub Desktop 选择 xiquanxiyu，检查变更后 Commit、Push origin。'
    Write-Host '仅小于90MiB的已检查文件进入普通Git。大文件保留，不绕过GitHub限制。'
    return
}
$delivery=Join-Path $root '最新版安装包-账号与小票-0.5.0'
foreach($target in @('win10-x86','win10-x64','win11-x86','win11-x64')){
    if(-not(Test-Path -LiteralPath (Join-Path $delivery ('Xiquan-Bathhouse-Setup-0.5.0-'+$target+'.exe')) -PathType Leaf)){throw 'Build all current installers before cleaning older artifacts.'}
}
& node.exe $helper eligible $root $clone $proof '-'
if($LASTEXITCODE-ne 0){throw 'Exact archive proof rejected; no deletion.'}
$verified=Get-Content -LiteralPath $proof -Raw -Encoding UTF8 | ConvertFrom-Json
$removed=@()
foreach($entry in $verified.entries){
    $resolved=(Resolve-Path -LiteralPath $entry.absolutePath).Path
    if(-not $resolved.StartsWith(($root+'\'),[StringComparison]::OrdinalIgnoreCase)){throw 'Deletion escaped project; stop.'}
    $cursor=Get-Item -LiteralPath $resolved
    while($cursor.FullName-ne $root){
        if($cursor.Attributes-band [IO.FileAttributes]::ReparsePoint){throw 'Reparse target refused; retained.'}
        $cursor=if($cursor.PSIsContainer){$cursor.Parent}else{$cursor.Directory}
    }
    $file=Get-Item -LiteralPath $resolved
    if($file.PSIsContainer -or $file.Length-ne $entry.size -or (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()-cne $entry.sha256){throw 'Local artifact changed; retain it.'}
    Remove-Item -LiteralPath $resolved -Force
    $removed+=$entry
}
# Only remove exact empty delivery folders, never recursively delete a tree.
foreach($name in @('最新版安装包-账号注册-0.4.9','最新版安装包-注册令牌-手机版1.2.8')){
    $folder=Join-Path $root $name
    if((Test-Path -LiteralPath $folder)-and @(Get-ChildItem -LiteralPath $folder -Force).Count-eq 0){Remove-Item -LiteralPath $folder}
}
$receipt=[ordered]@{RemoteCommit=$verified.remoteCommit;Removed=$removed;Retained=$verified.retained;Recoverable=$true;CompletedAt=[DateTimeOffset]::Now.ToString('o')}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ReportDirectory 'cleanup-receipt.json') -Encoding UTF8
Write-Host ('已清理已核实文件 '+$removed.Count+' 项；可从指定远端提交恢复。未核实文件全部保留。')
Write-Host ('清理回执：'+(Join-Path $ReportDirectory 'cleanup-receipt.json'))
