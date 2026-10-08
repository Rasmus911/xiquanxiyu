# 独立库存 0.4.4 / Android 1.2.3（code 10）发布

此流程在 Windows PowerShell 5 执行。候选构建仅使用原公开公钥；正式签名和发布由持有原密钥的人执行。库存数据库加法迁移和 ECS 部署由独立库存部署流程处理，禁止调用旧 Win11-only operations 聚合器。部署不会代替人工照片库存导入。

## 本地候选构建

先提交所有需要进入 SOURCE/WEB 的源文件。工作树存在已跟踪未提交修改会停止；无关未跟踪文件不会进入归档。

```powershell
Set-Location 'F:\溪泉洗浴系统'
& .\scripts\build-stock-release.ps1 -DryRun
& .\scripts\build-stock-release.ps1
```

默认使用四个经官方 SHA256 固定的离线运行时：`release/runtime-cache/stock-20261005`。六个目标必须全部成功：win7-x86、win7-x64、win10-x86、win10-x64、win11-x86、win11-x64。不会因云端策略不可达而阻断本地候选构建，也不会绕过缓存校验或替换运行时。失败保留构建目录；重试使用新 BuildId。

输出目录为 `F:\溪泉洗浴系统\最新版安装包-库存升级-0.4.4`，含真实六 EXE、对应 blockmap/latest.yml、delivery-index、stock-manifest、SOURCE/WEB ZIP、SHA256SUMS、PENDING.txt。目录已存在时停止，不覆盖旧交付。未取得正式 APK 时明确待办；候选不得发布更新频道。桌面更新清单签名与 Windows Authenticode 是两种独立签名，本流程不声称 Authenticode 已完成。

需要提前构建桌面以节省时间时，先由 `stock-source.cjs windows-inputs ROOT --output NEW_JSON` 保存桌面源文件逐文件哈希；运行通用六目标构建器后再保存新路径的快照并比较，两份必须完全一致。后续源提交只可改变不影响桌面输入的库存云端脚本。最终调用：

```powershell
& .\scripts\build-stock-release.ps1 -WindowsReleaseRoot '<实际六目标release根目录>' -WindowsInputsPath '<构建前且已与构建后比较一致的JSON>'
```

复用时仍检查当前已提交桌面输入和真实六载荷。不要用旧包、测试包、任意手写哈希清单冒充这次构建的证据。

## SOURCE/WEB 与后续云端工具约定

`build-stock-source.ps1` 从干净提交重新构建 client/mobile 页面，再调用已有可移植 ZIP 原语。只复制已跟踪且明确允许的源码及受限生成资产，不含生产 `.env`、私钥、签名库、历史安装包、`.superpowers` 或无关未跟踪文件。压缩的锁冲突只对同一已复制输入有限重试；回读每个 ZIP 条目，拒绝重复、遗漏、越界、链接及哈希不符。失败的库存 staging/ZIP 保留以供检查。

ZIP 根目录为 `xiquan/`。`source-manifest.json` schema 1 的契约字段：`source_commit`（40位提交）、`asset_source_commit`（相同提交）、`schema_head=20261005_independent_stock`、`required_migration=server/migrations/versions/20261005_independent_stock.py`、`desktop_version=0.4.4`、`android_version=1.2.3`、`android_version_code=10`、`files=[{file,size,sha256}]`、`production_ready=false`。清单内文件名相对 xiquan；shell 源文件在归档中统一 LF，哈希对应归档中的实际字节。

只读验证命令输出 JSON，错误返回非零：

```powershell
node .\scripts\lib\stock-source.cjs inspect 'F:\溪泉洗浴系统'
node .\scripts\lib\stock-source.cjs archive '<SOURCE-WEB.zip>' '<预期commit>'
node .\scripts\lib\stock-release.cjs validate '<release根目录>'
```

`stock-manifest.json` schema 1 绑定 `source_commit`、`build_id`、原 `trust_key_id=b26477a9ed540ad0`、三个版本字段、`mode=candidate|production`、六个 `targets`、`source_web={file,size,sha256}`、完整 `source_contract` 和 `android`（未完成时 null）。target 包含 target/arch/runtime/build_id/file/size/sha256/blockmap/updater_manifest。云端工具应验证实际 ZIP 与清单，不从 HTML 或服务器数据源推断提交。后续云端工具新增脚本应逐一注册到 source-security 精确列表。

## 人工原证书 APK 和原信任根签名

请保留原 keystore/alias。不要配置新证书，不开启 transcript/debug 日志；原密码环境变量未设置时，原构建器通过隐藏输入提示获取密码。以下只由人执行：

```powershell
& .\scripts\build-mobile-release.ps1 -Version '1.2.3' -VersionCode 10 -MinimumVersionCode 9 -ReleaseNotes '独立库存与手动耗材升级'
& .\scripts\lib\stock-mobile.ps1 -ApkPath '<新的xiquan-mobile-ordering-1.2.3.apk>' -PreviousApkPath 'F:\溪泉洗浴系统\deploy\cloud\mobile\downloads\xiquan-mobile-ordering-1.2.2.apk'
& .\scripts\sign-stock-release.ps1 -ReleaseRoot '<release根目录>' -PrivateKeyPath '<原加密私钥路径，位于release之外>' -ApkPath '<新的xiquan-mobile-ordering-1.2.3.apk>' -PreviousApkPath 'F:\溪泉洗浴系统\deploy\cloud\mobile\downloads\xiquan-mobile-ordering-1.2.2.apk'
```

已知 Android 包名 com.xiquan.mobileordering，原 code9 APK SHA256 `869e52d5d76265591ff7936f27706eacbb690df5afb7952a11b128eeba6af04c`，原证书 `15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9`。验证器通过 aapt/apksigner 检查真实包名、版本、非 debug 及新旧签名一致。最低 code9 为当前保留值；签名前仍须核对现有手机政策，不得降低已发布最低版本。

签名入口重新读取并用原公开信任根验证每个现有 Windows 策略，取严格大于六个旧 sequence 的新值，逐目标保留验证过的 minimumVersion。缺失、404、超时、伪造策略均停止；没有自动 sequence1，也没有猜测新渠道 bootstrap。须先取得可验证的现有策略，或另行设计明确的新渠道缺失证明协议。六个目标的隐藏私钥密码会分别提示；不保存密码。最终再验证所有签名、实际包、APK 原证书及新鲜策略，完成后 manifest 才变为 production。此 mode 只表示发布物签名门禁通过，不能替代 PG17/实机验收。

## 人工部署验收后才发布

使用 [完整 PowerShell 云端交接](2026-10-05-stock-cloud-handoff.md) 的库存专用入口，完成 PG17 备份、隔离恢复、加法迁移、旧数据逐项不变及角色检查。不得清空营业单、取消开放单或用旧业务替换脚本绕过条件。原有手机/Web policy、源码目录和下载内容必须保留。此次只提供人执行的脚本，未执行云端门禁。

随后人可使用：

```powershell
& .\scripts\publish-stock-release.ps1 -ReleaseRoot '<release根目录>' -PreviousApkPath '<原code9 APK>' -DryRun
& .\scripts\publish-stock-release.ps1 -ReleaseRoot '<release根目录>' -PreviousApkPath '<原code9 APK>' -StageOnly
# 完成云端/真实系统验收之后，以下命令才会上传并激活六个Windows频道：
& .\scripts\publish-stock-release.ps1 -ReleaseRoot '<release根目录>' -PreviousApkPath '<原code9 APK>'
# 重新生成一个新交付目录，包含已验证APK和六个签名envelope：
node .\scripts\lib\stock-release.cjs deliver '<release根目录>' '<新的正式交付目录>' '<原code9 APK>'
```

DryRun/StageOnly 都不执行 SSH/SCP；正式流程复用六频道发布器，检查签名/实际哈希/防回退并保留服务器当前 mobile/web 策略。APK/web 发布是独立人工环节，不能把此 Windows 发布命令当成手机已上线的证明。

Win7 仅 SP1，Electron22 已属旧版且没有当前安全支持；兼容性验证不等于安全支持承诺。Win11-x86 是运行于 64 位 Windows11 的 32 位应用，不代表有 32 位 Windows11，也不绕过系统硬件条件。六类真实系统、Android 原地升级和 USB 打印机验收仍须人工完成。收银/库存账号升级后需重新登录一次以取得五模块 JWT 范围，禁止绕过权限。

照片库存人工导入请使用 `docs/inventory/2026-10-05-photo-stock-import.md` 的受保护 HTTP 预览/确认流程，不能在数据库部署中自动导入或直接改库。
