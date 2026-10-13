# 0.5.1 实体卡消费交付

更新日志：1. 增加实体卡消费功能。

四个桌面包分别为 Win10/Win11、32/64 位；不包含 Win7。沿用原 AppID、公钥、最低版本与升级通道。云端是加法迁移，不清空订单、会员、余额、次数、库存和审计记录。当前安卓仍为 1.2.9/code16，已有 APK 不需要重新下载；网页与手机共用新后端。

部署修正：兼容 Docker Compose JSON 中以十进制字符串表示的内存字节值，同时保留严格的 API 512MiB/清理进程256MiB检查。旧API可以没有内存上限，部署后才安装新版限制；本次不要求先重启旧API。之前仅在preflight阶段停止、未生成维护job的，可以使用本修正版重新预检；不要续用旧stage。已进入维护阶段的仍必须按确切检查点恢复。

## 本机 PowerShell 完整操作

必须在 Windows 本机执行，不要粘到 ECS 的 bash。部署时暂停开单，先完成第一段，成功后才能执行第二段。账号、短信密钥、证书密码不要发到聊天里。

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $folder = 'F:\溪泉洗浴系统\最新版安装包-实体卡消费-0.5.1'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $folder '01-部署云端.ps1') -EcsTarget 'root@39.96.217.210'
    if ($LASTEXITCODE -ne 0) { throw '部署停止：保留输出中的 LOCAL_RECOVERY_IDENTITY 和 PRIVATE_DESKTOP_JOB，不要重跑部署或恢复旧数据库。' }
    Write-Host '云端部署完成，继续第二段。'
}
```

提示确认时输入 `UPDATE 0.5.1`。脚本自动预检、记录 stage、校验备份及隔离 PG17 恢复/并发证明、迁移和验证三端文件。阶段会实时打印；超时不自动重试。

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $folder = 'F:\溪泉洗浴系统\最新版安装包-实体卡消费-0.5.1'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $folder '02-签名并发布桌面更新.ps1') -EcsTarget 'root@39.96.217.210'
    if ($LASTEXITCODE -ne 0) { throw '签名或发布停止，保留错误输出。不要改发布序号或换密钥。' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $folder '03-验证三端与更新.ps1') -EcsTarget 'root@39.96.217.210' -CheckPublished
    if ($LASTEXITCODE -ne 0) { throw '最终验证未通过，请保留完整输出。' }
    Write-Host '发布验证通过；在旧桌面端登录页检查更新、下载并覆盖安装。'
}
```

发布确认输入 `PUBLISH 0.5.1`。原私钥位于本机 private/溪泉发布密钥/desktop-release-private.pem；四个通道会分别隐藏提示证书密码。脚本读取线上原签名策略，序号取四通道最大值加一，不猜序号1。构建日期不冒充发布日期，日志日期由已验证的正式签名策略更新。

## 停止后的恢复（不要盲目执行）

先确认错误原因已解决、云端没有仍运行的维护命令，再用第一段打印的**确切**本机身份文件恢复，不重新上传旧版本、不清维护状态、不回滚数据库。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\最新版安装包-实体卡消费-0.5.1\01-部署云端.ps1' -Mode resume -RecoveryIdentity '这里填写第一段打印的 LOCAL_RECOVERY_IDENTITY 完整路径'
```

恢复仅接受连续、匹配的私有检查点；缺失/冲突会停止并保留证据。已有 completed 证明不应重新部署。

## 逐项实机验收

| 项目 | 要检查的结果 | 当前界限 |
|---|---|---|
| 四个 Windows 目标 | 登录、USB打印、旧端检查更新覆盖后终端设置保留 | 实机未实测 |
| D5 读卡 | 焦点在等待刷卡窗口，315346091+回车只查询，不自动付款；前导零保留 | 硬件未实测 |
| 手机号/实体卡 | 同一会员余额和次数一致；补卡后旧卡不能消费 | 本地自动化覆盖，待真实云端验收 |
| 次卡/混合支付 | 次卡只抵独立门票，剩余现金/微信/支付宝/储值可组合，退款次数只返一次 | 本地自动化覆盖，真实PG17由部署脚本验证 |
| 旧业务 | 订单、会员、审计不被迁移改写；搓澡师小票/每日清理正常 | 部署保存并比较证明，待实机 |
| 手机与网页 | 原手机号账号登录、点单和库存同步；注册令牌入口保留 | 隔离API证明及线上路由校验，手机未实测 |

API 内存上限512MiB、清理进程256MiB。这是明确资源约束，不是完整负载测试；发生OOM/健康异常时保留检查点，不绕过资源或金额保护。

## 本机构建（仅源码以后改变时）

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\build-desktop-051.ps1'
```

需已提交且干净的源码、现有 Node/npm.cmd、已校验的 Electron43.7.7/44.5.1本地缓存和当前安卓1.2.9APK。已有交付目录不覆盖；源码变动后必须重构建，不能给旧字节贴新commit标签。

## 文件保留与归档

原发布密钥、数据库/.env、备份证据、.git、完整迁移链、依赖缓存与当前线上更新策略引用的旧文件均属于必需资料，不上传公共GitHub、不随意删除。旧公开交付按版本分类，超过90MiB按32MiB切分，GitHub Desktop推送后逐字节验证远端，再按确切叶文件清理。未取得远端证明的文件保留。
