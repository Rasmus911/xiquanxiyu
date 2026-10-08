[CmdletBinding()]
param([ValidateSet('cloud','desktop','android')][string]$From='cloud')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=$OutputEncoding
$steps=@('01-部署云端.ps1','02-签名并发布桌面更新.ps1','03-构建并发布安卓应用内更新.ps1')
$start=@{cloud=0;desktop=1;android=2}[$From]
Write-Host '0.4.8 更新：不清空订单、会员、次卡或库存。'
Write-Host '请关闭正在加单/收款的窗口，安排几分钟停写维护；密码只在本机隐藏提示中输入。'
if($From-ne 'cloud'){
    if((Read-Host '只有前面的步骤已成功才可跳过。确认输入 PREVIOUS STEPS OK')-cne 'PREVIOUS STEPS OK'){throw '已取消，没有开始发布。'}
}
for($step=$start;$step-lt $steps.Count;$step++){
    $path=Join-Path $PSScriptRoot $steps[$step]
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw ('缺少脚本：'+$path)}
    Write-Host ('正在执行：'+$steps[$step])
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $path
    if($LASTEXITCODE-ne 0){throw ('失败：'+$steps[$step]+'。已停止后续步骤，请保留完整输出及PRIVATE_DESKTOP_JOB，不要重复部署或恢复旧数据库。')}
}
Write-Host '脚本成功返回。请在旧桌面登录页检查更新，在旧手机APP内检查更新并确认覆盖安装。'
Write-Host '实机验收：加单耗材弹窗、10项分页、成本首次赋值与后续本人密码、会员余额和次卡次数保持。'
