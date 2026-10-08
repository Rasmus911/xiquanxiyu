# 独立库存人工上线：完整 PowerShell 交接

本文件的命令由持有原密码/密钥的人执行。此次只交付本地脚本，没有执行 SSH、上传、云端迁移、照片导入或正式发布。实际 PG17 门禁必须在生产 DDL 前通过；语法检查不等于已通过这些门禁。不运行旧 operations 业务替换/8004 清空脚本，不关闭或取消现存营业单来满足旧条件。

## 1. 本地六包与最终源码

六个实际 EXE 已由控制任务构建，平铺在 `F:\溪泉洗浴系统\最新版安装包-库存升级-0.4.4`。原始验证/签名输入仍是下述 release 根目录。云端脚本提交完成后，最终 SOURCE 必须包含这个最终提交；不重复构建六 EXE。

```powershell
$ErrorActionPreference = 'Stop'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Set-Location 'F:\溪泉洗浴系统'
$release = 'F:\溪泉洗浴系统\release\windows\0.4.4\stock-fast-20261005-6c1e397a'
$previousApk = 'F:\溪泉洗浴系统\deploy\cloud\mobile\downloads\xiquan-mobile-ordering-1.2.2.apk'
# 已有 stock-manifest.json 时直接使用交付好的源码包，不重复制包。
if (-not (Test-Path -LiteralPath (Join-Path $release 'stock-manifest.json'))) {
  & .\scripts\build-stock-release.ps1 -WindowsReleaseRoot $release `
    -WindowsInputsPath '.\release\runtime-cache\stock-20261005\windows-inputs-before.json' `
    -OutputDirectory 'F:\溪泉洗浴系统\最新版安装包-库存升级-0.4.4\发布资料'
}
# 从实际 manifest 解析精确文件，禁止猜测 latest ZIP。
$manifest = Get-Content -LiteralPath (Join-Path $release 'stock-manifest.json') -Raw | ConvertFrom-Json
$source = Join-Path $release $manifest.source_web.file
$sha = [string]$manifest.source_web.sha256
$commit = [string]$manifest.source_commit
node.exe .\scripts\lib\stock-source.cjs archive $source $commit
if ($LASTEXITCODE -ne 0) { throw 'SOURCE verification failed' }
```

如果 `$source` 不存在，先检查 manifest 的实际文件和构建结果，不能替换成另一个旧 ZIP。SOURCE/WEB 候选允许先部署，正式 APK/桌面签名是后面的独立阶段。

## 2. 只读发现、上传和维护确认

```powershell
$common = @{BundlePath=$source;ExpectedSha256=$sha;SourceCommit=$commit}
& .\scripts\invoke-stock-upgrade.ps1 @common -Mode preflight -StageOnly
# StageOnly 到此为止，零 SSH/SCP。以下由人执行真实上传与只读预检。
& .\scripts\invoke-stock-upgrade.ps1 @common -Mode preflight
```

工具固定 ECS `root@39.96.217.210`，项目 `/opt/xiquan/xiquan`。上传实际六个 Python 文件和 ZIP，再逐文件核对远端 SHA256，最后执行简单的 `python3 /tmp/.../stock_deploy.py ...`，没有拼接内联 Python。每个 native 非零退出都会停止。

保存输出中的精确 `stage`。预检现场读取实际 PG major/head、reset、maintenance 和策略版本。只接受直接前驱 `20261004_catalog_packages` → `20261005_independent_stock`；其他 head（包括已迁移和未知部分状态）停止，不能改 head 字符串蒙混过去。现存开放营业单和手牌不会阻止本次加法迁移。

```powershell
$stage = Read-Host '粘贴此次输出的完整 /opt/xiquan-releases/stock-stage-...'
& .\scripts\invoke-stock-upgrade.ps1 @common -Mode deploy -Stage $stage
# 随后输入明确显示的 MAINTENANCE <完整commit>，同意暂时停止 API 写入。
```

工具依次执行以下实际门禁，任一步失败立即停止：

1. 精确 SOURCE/tool 哈希、原运行身份、一个 API、独立角色、旧镜像依赖与 PG17 工具；采用本人确认的低内存预算：维护进程/镜像探针上限 384 MiB，恢复库上限 256 MiB，另留 128 MiB 余量。单进程阶段至少可用 512 MiB，恢复阶段至少可用 768 MiB；停 API 前后和每次隔离恢复启动前重新测量，输出实际内存和磁盘余量。仍要求备份盘空间 6 GiB，不新增 Swap 或自动清理。原镜像不足时停止，不自动联网安装。数据库较大或实际限额不足时停止，不跳过恢复验证；人工预留至少完整库/索引体积数倍的额外磁盘。
2. 固定现有镜像 ID，仅离线复制此次 app/migrations 源码，新镜像逐文件哈希比对；不重复 Docker 拉取/pip 网络构建。生产停止 API 后通过独占 barrier 取得独有维护 UUID，外部维护或待处理 reset 无权接管。
3. 当前旧结构一致性备份，实际恢复至唯一 PG17 容器/卷，私有独立网络、无宿主端口、限制 256 MiB/1 CPU，禁用该临时库的并行 worker，降低该临时库缓存（不修改生产 PostgreSQL 设置）。恢复步骤串行，旧恢复容器停止后才启动下一只；逐表完整数据及审计链比对。生产维护不释放。
4. 隔离副本创建专用测试登录，运行唯一库存 migration；精确比较全部旧表、旧列、旧值，仅允许三张新表和 `order_items.inventory_mode`。检查旧库存映射、历史单据 legacy 模式、原角色 LOGIN/密码摘要/权限身份和旧对象 ownership 不变。副本上的角色初始化 SQL 不会在生产重跑。
5. 保存副本保全证明后，才在副本上写专用临时库存：两个真实 runtime 数据库连接通过真实 financial lock、row lock、stock service 竞争最后 1 单位，必须一次成功、一次拒绝，成功请求重试不再扣减；实际不可变表 UPDATE/DELETE/TRUNCATE 和 runtime CREATE TABLE 均须被拒绝。此项是服务层真实 PG17 证明，不冒充真实用户 HTTP 登录/实机验收。
6. 再核验生产完全未变；实际 owner 登录、独占 barrier、固定 revision 范围的受保护 migration 入口执行生产 DDL。迁移代码、Alembic head 和保全检查同一事务，失败回滚该事务；不执行数据导入、业务替换、seed 或 reset。保留 PostgreSQL 已有账户密码和 LOGIN，不对生产运行会设置 NOLOGIN 的旧角色脚本。
7. 新结构备份，再做实际 PG17 完整恢复证明。保存 `ready.json` 后复制已验证 server 与 Web/mobile 资产，保留 `.env`、证书、旧下载、配置、全部更新 feed、全部备份；资产 0755/0644，先资源后原子替换 HTML。
8. 固定新镜像启动一个 API；normal runtime 不持 owner URL、禁止 DDL/bootstrap/seed。检查健康、真实镜像、实际 schema/roles、公共 Web/mobile 所有资产 SHA256 和保留下载/feed；全部通过后才用本 job UUID 解除维护。照片库存尚未导入，安装包尚未发布。

保留所有 `PRIVATE_STOCK_JOB`、phase、备份、恢复容器/卷和私有诊断；没有自动清理。错误显示 phase 和证据路径。诊断可能含私密运行信息，只在服务器本地查看，不要粘贴完整 `.env`、command-failure 文件、JWT 或密码到聊天。

## 3. 有界恢复

生产迁移前或迁移中失败：保持停止，依据该 phase 人工判断，不重跑 deploy、不盲目 pg_restore、不启动旧 API。支持的 resume 仅限已有 `ready.json`（新结构备份恢复已验证）、完整 `after.json` 保全摘要、同一源码/tool/image、同一维护 UUID，处理源文件切换或新 API/静态健康失败。它不会重建镜像、重复迁移、导入、清库或恢复 dump。

```powershell
$job = Read-Host '粘贴该次 PRIVATE_STOCK_JOB /opt/xiquan-backups/stock-cutover-...'
& .\scripts\invoke-stock-upgrade.ps1 @common -Mode resume -Stage $stage -Job $job
```

不满足上述精确条件会停止并保留证据。释放维护后记录完成文件之前中断也不猜测恢复；需人工检查当前业务写入与维护状态。

## 4. 正常登录、照片库存预览与应用

确认健康后，收银/库存账户退出并重新登录一次以取得新五模块 JWT 范围。使用实际授权账户及原隐藏密码，不能注入角色、硬编码 JWT 或绕过 channel/policy。三名既有手机管理员 `18631459666`、`18603346509`、`15133863898` 各自在真实手机验证原密码登录、对应权限和会话；不要在 PowerShell 命令行传密码。

```powershell
$env:PYTHONUTF8 = '1'
$username = Read-Host '现有库存授权用户名'
$terminal = Read-Host '现有已启用 desktop terminal code'
$list = Read-Host '新的库存列表 JSON 完整路径'
$mapping = Read-Host '人工审阅的 mapping JSON 完整路径'
$preview = Read-Host '新的 preview JSON 完整路径'
$receipt = Read-Host '新的 receipt JSON 完整路径'
$csv = '.\docs\inventory\2026-10-05-photo-stock-review.csv'
$cli = @('--api-url','https://api.pqxqxy.xyz/api','--username',$username,'--terminal-code',$terminal)
& .\server\.venv\Scripts\python.exe .\scripts\stock_import.py @cli list --output $list
if ($LASTEXITCODE -ne 0) { throw 'Inventory list failed' }
# 参照 docs/inventory/2026-10-05-photo-stock-import.md，先人工填写真实UUID/create映射。
& .\server\.venv\Scripts\python.exe .\scripts\stock_import.py @cli preview --csv $csv --mapping $mapping --output $preview
if ($LASTEXITCODE -ne 0) { throw 'Inventory preview failed' }
# 审阅16条ready和27条排除；4箱×200袋=目标800袋，不是额外增加800袋。
& .\server\.venv\Scripts\python.exe .\scripts\stock_import.py @cli apply --csv $csv --mapping $mapping --preview $preview --output $receipt
if ($LASTEXITCODE -ne 0) { throw 'Inventory apply stopped; retain preview and receipt evidence' }
```

CLI 每次隐藏输入密码，apply 还要求 `APPLY <source_sha256>`。不自动覆盖确认文件，不修改未提及库存、开放单、账户、金额或历史审计。

## 5. 原密钥构建、签名与真实验收

```powershell
# 只有原密钥持有人执行；不开 transcript/debug、不把密码放命令行。
& .\scripts\build-mobile-release.ps1 -Version '1.2.3' -VersionCode 10 -MinimumVersionCode 9 -ReleaseNotes '独立库存与手动耗材升级'
$apk = 'F:\溪泉洗浴系统\deploy\cloud\mobile\downloads\xiquan-mobile-ordering-1.2.3.apk'
& .\scripts\lib\stock-mobile.ps1 -ApkPath $apk -PreviousApkPath $previousApk
$privateKey = Read-Host '原加密桌面私钥路径（release目录之外）'
& .\scripts\sign-stock-release.ps1 -ReleaseRoot $release -PrivateKeyPath $privateKey -ApkPath $apk -PreviousApkPath $previousApk
```

原 APK code9 SHA256 `869e52d5d76265591ff7936f27706eacbb690df5afb7952a11b128eeba6af04c`；原证书 `15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9`；桌面原公钥 ID `b26477a9ed540ad0`。签名器重新验证六个现有签名策略并逐目标保留最低版本；404/超时/未知渠道停止，不推断 sequence1。APK 签名和 Windows 更新 envelope 签名都不等于 Windows Authenticode。

由人完成 Win7 SP1/Win10/Win11 x86/x64 六环境安装升级、Android 原证书覆盖升级、实际 USB 打印、新旧开放单继续结账/撤销、手动耗材/库存版本冲突/权限、余额会员金额不变、三名手机管理员登录。记录结果；没有实机结果时不得标记验收通过。Win11 x86 包在64位系统运行，Win7/Electron22 为旧版支持边界。

## 6. 验收后正式发布

```powershell
& .\scripts\publish-stock-release.ps1 -ReleaseRoot $release -PreviousApkPath $previousApk -DryRun
& .\scripts\publish-stock-release.ps1 -ReleaseRoot $release -PreviousApkPath $previousApk -StageOnly
# 以下正式上传/激活六Windows频道，只在人确认实际验收后执行。
& .\scripts\publish-stock-release.ps1 -ReleaseRoot $release -PreviousApkPath $previousApk
# 手机发布独立，保留Windows频道并通过现有防回退/资产门禁。
& .\scripts\publish-mobile-release.ps1 -Version '1.2.3' -ValidateOnly
& .\scripts\publish-mobile-release.ps1 -Version '1.2.3' -StageOnly
& .\scripts\publish-mobile-release.ps1 -Version '1.2.3'
# Web内容已由精确SOURCE部署；用同一commit生成公开版本政策与本地发布目录。
& .\scripts\build-web-release.ps1 -BuildId $commit -ReleaseNotes @('独立库存与手动耗材升级')
# 检查重建的每一个原SOURCE Web资产，任一不同则停止重新验收。
foreach ($asset in @($manifest.source_contract.files | Where-Object { $_.file.StartsWith('client/dist/') })) {
    $file = Join-Path '.\deploy\cloud\web' $asset.file.Substring('client/dist/'.Length)
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) { throw 'Web asset differs from accepted SOURCE' }
}
& .\scripts\publish-web-release.ps1 -EcsTarget 'root@39.96.217.210' -DryRun
& .\scripts\publish-web-release.ps1 -EcsTarget 'root@39.96.217.210' -StageOnly
& .\scripts\publish-web-release.ps1 -EcsTarget 'root@39.96.217.210'
node.exe .\scripts\lib\stock-release.cjs deliver $release 'F:\溪泉洗浴系统\最新版安装包-库存升级-0.4.4\正式发布资料' $previousApk
if ($LASTEXITCODE -ne 0) { throw 'Formal delivery verification failed' }
```

正式发布可能逐频道完成；出现失败保留每一频道证据，不据单个成功推断全部上线。原始 release 验证根目录保留，不拿只含交付物的平铺目录代替验签输入。
