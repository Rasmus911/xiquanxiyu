# 2026-10-04 营业升级实施记录

状态：开发中。用户选择原目录内、当前会话逐项实现，不使用子代理；开发分支 `feat/operations-upgrade-20261004`。Win11 0.4.3 / Android 1.2.2 原签名安装包已由用户构建；用户已完成历史云数据库备份的独立PG17恢复测试。新版本尚未云端部署，代理从未连接ECS或修改生产数据。下方早期“尚无安装包”记录是当时阶段状态，以本段和末尾最新记录为准。

最新范围：桌面只构建Win11 64位，安卓仍交付；重点验收于在跃、李丽娜、于景辉已有绑定管理员手机登录/通道与管理权限。保留其他桌面历史包，不清云端业务数据。

## 源码安全基线

只把 `scripts/lib/source-security.cjs` 明确列出的源码、配置原型和测试加入Git。该文件的枚举器不遍历private、旧临时SSH脚本、生产配置或构建包；敏感内容报告只显示文件、行号和规则。

```powershell
Set-Location -LiteralPath 'F:\溪泉洗浴系统'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\prepare-source-baseline.ps1' -ValidateOnly
```

私钥、实际.env、Android keystore、数据库/备份/日志、下载和安装包不进Git。不创建远程仓库、不推送。scanner是辅助检查，不是全部安全保证。

## 验证记录

- 原手机端基线：21个测试文件、84项通过（2026-10-04本地测试）。
- 原后端基线229项通过；pytest缓存写权限警告1条，后续测试禁用cacheprovider，不删除用户缓存。
- 原桌面Vue82项、Electron/运行时68项通过。
- R1安全检查器已观察红测；8项绿测通过。白名单纳入必要的NSIS模板和Docker构建忽略文件。较早操作文档保留本地，不把未审阅旧命令示例纳入新Git基线。
- 首次源码基线发现原文件已有尾部空格、空白末行及CRLF差异；只在这次未修改业务源码的基线提交中排除这三类历史空白检查，保持原文件。之后新增业务改动使用正常差异检查。

后续权限、点单、资金、数据替换和发布均按[总计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-upgrade.md)记录真实结果；云端步骤和用户隐藏签名输入尚未执行。

## 权限实施

A1–A3作为安全依赖同批验证：服务员工获得桌面只读/点单模板时，必须同时接入浴区和目录对象范围，不能只提交新模板而留下旧API全量读取。原先“服务员工没有桌面手牌入口”的测试更新为“仅能读取自己的已激活浴区”；越权仍拒绝，联动字段不泄漏另一浴区。

已观察员工生命周期9项红测、对象范围17项红测、手机真实撤销3项红测。固定入口字段、UUID绑定管理员与普通员工授权、动作错误与会话错误分离正在回归。最高管理账号仍可销售历史未分类的可售项目，未分类不会授给普通服务员工。

A1–A3第一轮全量后端281项通过；随后新增“换到另一浴区后重放旧加单”红测，修复手机幂等重放仍须验证当前对象范围。手机HTTP15项和桌面HTTP10项通过。没有更改云端账号的密码或绑定。

A4已完成：授权表单同时保存入口与启用状态，普通员工可逻辑删除，绑定管理员和当前账号受保护；桌面菜单与页面动作消费服务器能力。桌面Vue97项、Electron/运行时68项、type-check通过。旧后端未返回页面权限时明确提示更新云端，不用角色兜底授予全部页面。

A5已完成本地实现：库管手机入口仅库存；绑定最高管理员手机可点单、报表、入库；登录通道、动作拒绝与会话撤销使用不同错误提示。手机98项及type-check通过。新增只读UUID/终端诊断CLI，不改账号密码或绑定。后端全量第一轮285项通过、1项旧错误码断言失败，已修正断言并重新验证相关模块；云端绑定和手机实机仍待用户部署后核对，不能视为线上已恢复。

B1/B2已观察红测并完成本地实现：真实memory-router A→B→C乱序响应、延迟Electron忙状态握手造成A串到B均已复现并修复；各账单UUID独立草稿，旧会话回应不能清新草稿；网络不确定重试保留原版本、数量和幂等键。服务端过期version拒绝且订单/库存不写，原key重放返回原结果。手机切换、结清同号新UUID、登出与不确定重试共6项通过。提交移到快速加单标题右侧，默认全部混排，服务一次/商品数量步进，缺货不可售、输入控件不冒泡。

B1/B2阶段全后端288项、桌面Vue108项/Electron68项、手机102项通过，双端type-check/build通过。这是本地构建，不是签名EXE/APK；尚未做实机窄屏/打印或云端验收。B3新增全量CAS排序API仍在验证，未以SQLite冒充PostgreSQL并发结果。

B3/B4本地回归：后端302项、桌面Vue112项/Electron68项、手机106项和双端build通过。完整目录集合、CAS revision、重复/缺失/票ID拒绝、仅UUID绑定管理员可排列、手机排列不能顺带改价均有API测试；鼠标/触屏Pointer事件、上移/下移、取消不写、409保留编辑和旧会话隔离有DOM/组合测试。没有手机实机结果。当前未发现本地docker/psql/pg_ctl命令，PostgreSQL并发与维护角色验收仍需独立实例，正式发布不能用SQLite结果代替。

C1正式42项定义、完整名称/时长/价格、7组包含额度、3种库存耗材和岗位范围的两项字典比对测试通过。定义尚未接入启动种子，不会自动替换已有目录。

C2新增持久浴区/退役状态、目录稳定码/套餐定义及订单包含额度/套餐引用字段。结构迁移不替换号码、价格、库存、余额和历史消费；已结账新增字段仍受SQL不可变守卫保护，同人/同经营期套餐引用受约束。独立迁移及财务守卫38项通过；本阶段后端全量311项通过（2026-10-04，174.80秒），随后补充真实历史审计链迁移断言并单独回归。PostgreSQL角色与并发仍未验收。

C3本地维护预检/切换、私有备份receipt校验及空库种子已实现。未结账/结算中/未解决挂失/重置待运行/编号或澡巾冲突均阻止切换；同一物理连接排他锁内切换，失败不留下半套目录且维持维护状态。Windows ACL实际检查、目录穿越、损坏/过期/未恢复凭据均有隔离测试。普通API不获得owner连接或operations_private卷，维护进程不注册公开业务API/Socket、不启动重置线程/短信。旧120手牌测试迁移到明确的legacy_seed夹具，新空库100牌/42项/新品库存0；现有库启动不补回删除或停用数据。后端340项通过、1项PG集成因无独立PG17而跳过（223.01秒）。真实PG角色/并发和实际备份恢复仍是正式发布门槛，不以fixture receipt冒充已恢复云端备份。

C4逐人成人/儿童门票已接入单人开牌、多人联动开牌和未结账换票；已有激活客人保留原票，退役手牌不能重新开牌。票价由服务端计算，换票保留原行并审计、检查账单版本和幂等请求；桌面切换手牌时关闭旧票种弹窗，延迟结果不能写入另一账单。44项相关后端测试通过，完整后端355项通过、1项PG跳过（222.55秒）；桌面Vue123项及Electron68项、手机106项通过，双前端type-check/build通过。新签名安装包、手机实机、云端绑定及PG验收仍未执行。

C5纯Decimal包含额度计算和金额写锁已实现，服务/商品实际数量不变；多张同项目按稳定顺序覆盖，成人儿童共用一次额度，非法数值和重复slots拒绝。加单、开牌、挂失/恢复、调价、结账/退款、会员与库存写入沿用“权限→共享维护屏障→金额串行锁→行锁”，直接服务调用同样保护。新增28项计算/锁顺序测试通过；全量后端第一轮380项通过、1项PG跳过（230.66秒），随后补充库管403不能进入金额锁的真实账号测试并回归相关28项。PG真实竞争仍未验收，SQLite只证明程序边界与顺序。

C6套票API及双端选择/替换/取消已接入，最多一个活动父订单；实际项目按快照免相应额度，不凭空创建商品销售。额外件数收费、同key重试、客户端金额拒绝、库存不二次出入库、逐人换票及未结账调价均有真实API测试。双端选包保留其他服务/商品草稿，替换确认进入不可变请求；手机取消已做真实Vue页面测试。后端第一轮402项通过、1项旧手机scope断言需纳入新增套票授权、1项PG跳过（232.64秒）；该断言已明确更新，访问策略和套票单独回归。桌面126项/Electron68项、手机111项通过，双端build通过；追加的异常类型/过量精度边界仍继续回归，不把单元测试当实机及正式签名安装包。

C7本地回归：后端414项通过、1项PG17隔离测试跳过（237.96秒）；桌面Vue127项/Electron70项、手机111项通过，双端type-check/build通过。包含额度小票使用服务器净额，58mm真实生产HTML的转义、补打和额外份数已有测试；现金/储值结账和幂等重放、报表不重复流水、分人结清后历史价快照不改、金额异常及重复套餐父行定位共8项真实API/账本测试通过。修复换票旧请求释放了另一笔新忙状态的问题，真实Vue路由/延迟请求回归通过。C6追加数量精度/数值边界及权限模块77项回归通过。本地功能验收不等于PG并发、实际备份恢复、原证书签名、Win11/手机实机或云端已部署；这些仍留在发布门禁。

## 单一Win11发布流程（R2早期记录，实际构建见最新记录）

本次桌面源码版本为0.4.3，Android源码版本为1.2.2/code9；没有生成这些版本的正式EXE/APK，也没有上传。六目标基础工具默认契约保留；新入口显式传`win11-x64`，从签名、ZIP、暂存到公开校验都只处理请求目标。单目标发布不会覆盖旧Win10过渡入口、其余五通道或手机/Web策略。0.4.2旧六包目录保留。

本地验证：桌面Vue127项、Electron/运行时73项、手机111项及双端type-check/build通过；发布Node测试30项、实际PowerShell包装器的单包/六包ZIP与StageOnly检查通过。测试安装包和签名都来自隔离fixture，不是新的可用生产安装包。SOURCE/WEB生成器实际ZIP回读/逐项SHA、原commit身份、禁止私密/更新文件、拒绝脏源码和旧包不覆盖均已测试；新入口的原公钥、版本及无写入预检通过。遵守用户不派代理要求，按review技能清单自行复查；未做独立第二人审查。

2026-10-04补充：完整签名预检原先把待构建的0.4.3作为旧策略验证的当前版本，导致旧0.4.2被错误拒绝。现先独立验证旧策略签名，再比较新版版本及序号严格递增；未降低客户端实际更新的防回退校验。新增回归覆盖有效旧策略、相同/更高版本、重复/回退序号、篡改签名和错误目标；实际旧0.4.2原公钥策略的完整ValidateOnly也通过（仅本地旧文件验证，不代表已核对线上最新序号）。未读私钥、未生成新安装包、未上传或变更云数据库。

2026-10-04用户构建报错修复：SOURCE/WEB必需文件清单错误引用不存在的`catalog_definition.py`，实际价目表模块是`catalog_defaults.py`。清单现使用真实模块，并要求套票计费和服务模块一并存在。隔离ZIP测试改用与真实模块一致的路径且核对ZIP内三项源码，先复现原报错再验证修复；30项发布Node测试仍通过。没有创建空文件绕过检查，也未降低已提交源码、原签名或禁止私密配置入包的门禁。

离线入口`-OfflineRuntimeCache <绝对目录>`仅支持已核实的44.5.1/x64档案pin，缺失/错误即停止，不转入网络模式，也不删除原档案；普通模式仍校验官方SHASUMS。此次没有实际下载157MB档案或构建完整新SDK/NSIS，只有隔离档案与解压边界测试，不能当成完整安装包构建结果。

手机`public/download-config.json`为生成的公开下载元数据，已从Git索引移出并忽略，本地原文件保留；它不再冒充新源码发布里的已签名APK。新安装包集中目录也在Git忽略范围内。

### 用户本机构建入口

先核对最新线上签名策略。代理当前无法读取公开策略（HTTPS请求失败，不代表ECS一定故障），不能确认线上序号或是否已有更高版本。用户保存实际`/releases/desktop/win11-x64.json`为本地公开JSON，并提供比它更高的发布序号；入口验证原公钥签名、版本和序号，失败停止。构建中不连接SSH、不执行生产迁移。

```powershell
Set-Location -LiteralPath 'F:\溪泉洗浴系统'
$oldRelease = 'F:\溪泉洗浴系统\release\windows\0.4.2\windows-042-offline-20261003-235751-954d178e'
$publicKey = Join-Path $oldRelease 'release-public-key.pem'

# 只做无写入预检，不读私钥、不要求签名密码：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\build-operations-release.ps1' `
    -PublicKeyPath $publicKey -SkipSigning -ValidateOnly
if ($LASTEXITCODE -ne 0) { throw '预检失败，停止' }

# 完整本机构建前，必须使用已核对的最新线上策略文件，不以旧本地文件猜线上序号。
$policyPath = Read-Host '最新线上Win11签名策略JSON的本机绝对路径'
$sequence = [int](Read-Host '填写比该策略sequence严格更大的发布序号')
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\build-operations-release.ps1' `
    -PublicKeyPath $publicKey -PreviousDesktopPolicyPath $policyPath -Sequence $sequence `
    -PrivateKeyPath 'F:\溪泉发布密钥\desktop-release-private.pem' `
    -PreviousApkPath 'F:\溪泉洗浴系统\release\mobile\xiquan-mobile-ordering-1.2.1.apk'
if ($LASTEXITCODE -ne 0) { throw '本机构建或签名失败，禁止上传，保留已生成文件供核对' }
```

仅在用户本机正式执行第二段时，桌面发布密钥及Android原证书密码由隐藏提示输入；不要发到聊天。不换证书、不要求卸载员工旧APP。若持有已校验的缓存目录，在最后构建命令增加`-OfflineRuntimeCache '实际绝对目录'`；不得只凭ZIP文件名相信缓存。

成功后的集中目录**预计**为`F:\溪泉洗浴系统\最新版安装包-0.4.3`，含一个Win11-x64 EXE、一个原证书APK、SOURCE/WEB ZIP与BUILD-STATUS。实际路径、SHA和签名结果以真实执行输出为准。`operations-manifest.json`保留PG17/恢复/实机未验收状态，不能因为签名成功就标记全部可上线。R3受控维护部署及R4精确清理实现尚未交付，不运行旧通用update脚本覆盖本次结构或手工清空云端数据。

## 最新记录：真实产物与备份恢复

- 原客户端交付源码：`ac4b0397bedeb99d2ba7e71eb1984ce6c8d13bc5`；build_id=`operations-offline-20261004-190513-bb38f4aa`。
- Win11 x64 0.4.3：`Xiquan-Bathhouse-Setup-0.4.3-win11-x64.exe`，SHA256=`51b683b4aa06b06d94ca423d3f374d341614431558dd2d2a11132b85e828dcb7`。
- Android 1.2.2/code9：`xiquan-mobile-ordering-1.2.2.apk`，SHA256=`869e52d5d76265591ff7936f27706eacbb690df5afb7952a11b128eeba6af04c`。原签名证书SHA256=`15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9`，不重新签名或换证书。
- 集中安装包目录：`F:\溪泉洗浴系统\最新版安装包-0.4.3`。实际签名/载荷目录：`F:\溪泉洗浴系统\release\windows\0.4.3\operations-offline-20261004-190513-bb38f4aa`。集中目录的安装包为平铺文件，不把它误当含`win11-x64`子目录的签名发布根。
- 用户回传的私有备份：`/opt/xiquan-backups/pre-operations-8X2UMTRi/database.dump`，SHA256=`832feb37b3cd82235a13a27852ed379d702e1df41c8d7e14d5c1aff2df377dbb`。
- 用户实际恢复到独立PG17容器成功，报告：`/opt/xiquan-backups/restore-test-VEHRqEGW`；审计285条，审计尾哈希`65d5bb9e7a7248a09c5767e5fe7f26a6ef5e5bdd51403450447b3f1c0b4884e2`，经营期`7865d566-4a55-4608-aca5-49a4eadee12b`，经营修订479。测试库和生产实际server identifier不同，测试资源保留，不清理。
- 该历史恢复验证证明该dump可恢复；不等于新版结构/角色/并发验收或迁移后业务替换前的verified receipt。没有将安装包manifest的`pg17_restore`/实机字段伪改为passed。

## R3检查点：部署源码准备，不是生产切换

当前已提供私有`operations-backup create` / `verify-restored`维护CLI：导出同一个PG事务快照，read-only pg_dump导入该快照；比较实际不同的PG17 server identifiers、每一张public表的行数/完整行哈希、金额/库存/历史记录和真实审计链。只有源快照未变化、独立恢复结果完全匹配时才另建0600 receipt；pg_restore --list永远只是格式检查。其本地守卫测试21项通过；新版CLI在实际PG17上的端到端验证仍待维护工具容器执行，不能冒称已执行。

`scripts/build-operations-deploy.ps1`在唯一临时目录用**本地Git已提交快照**构建SOURCE/WEB，不reset、不移动用户原文件，不把当前未提交的`mobile/version.json`格式变化纳入源码SHA。沿用已有网页构建，不重做EXE/APK，原压缩包保留；尚未提交的新部署源码会明确停止。输出是新的唯一SOURCE/WEB ZIP及公开索引JSON。

`scripts/upload-operations-upgrade.ps1`当前仅支持**源码暂存和只读preflight**：

- `-StageOnly`：本地真实ZIP清单、所有文件SHA和外层SHA验证，无SSH/SCP，无云修改。
- 正常执行：在云端创建随机0700上传目录，上传唯一包和已校验小工具；两份远端SHA均正确后才运行只读检查。
- 读取现有PG17、旧schema、真实容器/worker状态、未结清/挂失/重置阻塞，以及三个既有管理员UUID/手机号/绑定，不自动按姓名或role新增最高权限。
- 将所有SOURCE/WEB文件解压到唯一私有`/opt/xiquan-releases/operations-stage-*`，不覆盖项目、.env、nginx active.conf、更新策略、EXE/APK下载或任何业务表。保存受保护公开引用的hash/inode，只读报告路径在输出中。
- **没有apply模式**。不能据此声称结构迁移、正式42项目录/100牌替换、三位手机管理员登录或资金核验已完成。受控容器编排、两阶段真实恢复receipt、用户确认预览后的切换以及R4清理仍待后续交付。

用户下一步运行（每个失败都停止，不用旧update.sh）：

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'F:\溪泉洗浴系统'
    $bundle = & '.\scripts\build-operations-deploy.ps1'
    if (-not $bundle.ZipPath) { throw '没有有效源码包，停止' }
    & '.\scripts\upload-operations-upgrade.ps1' -BundlePath $bundle.ZipPath -ExpectedSha256 $bundle.Sha256 -StageOnly
    & '.\scripts\upload-operations-upgrade.ps1' -BundlePath $bundle.ZipPath -ExpectedSha256 $bundle.Sha256
}
```

如果本机执行策略阻止直接调用脚本，用`powershell.exe -NoProfile -ExecutionPolicy Bypass -File`形式分别执行，或采用本次聊天中给出的完整入口。成功标记`SOURCE_STAGE_AND_READONLY_PREFLIGHT_OK`；保存`stage_directory`、`report_path`、三位`mobile_administrator_checks`及手牌阻塞结果，再进入维护窗口步骤。不要提前删除原备份、停止容器或手工恢复进生产库。

本次检查点本地验证：完整后端回归453项通过、1项实际PG17隔离测试因本机没有明确授权的可丢弃PG17而跳过（248.87秒）；新增预检文件的后续两项测试纳入单独20项回归通过，备份CLI守卫21项通过。真实PowerShell源码快照/上传包装器测试通过；SSH/SCP仅在传输边界使用隔离替身，未连接ECS。源码安全8项及发布14项Node测试通过。原签名Win11发布集合和真实EXE/APK文件哈希再次核验，保持上述两个SHA不变。依用户要求不派代理，自行复查，未进行独立第二人审查。以上不代表新版PG17备份CLI端到端、云端切换、三位手机账号或实机打印已通过。

## 用户已完成暂存；独立正式切换入口

用户回传真实暂存目录`/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54`，SOURCE/WEB提交`56a4d0eeaf552a4f78ef87f1ee76e4fa0b8107f5`；三个手机号管理员的既有UUID均active/identity_matches/highest_binding=true，因此不修改账号、密码或策略。初次检测8004有一笔未结，用户随后表示已处理；切换入口仍会重新读实际状态，不代替用户结账或强清。

正式入口`scripts/invoke-operations-cutover.ps1`只上传三个经本地/远端SHA验证的小工具，沿用该SOURCE/WEB目录，不重建EXE/APK，不再反复上传源码包。`-StageOnly`只检查本机工具/参数，无SSH。用户执行`-ApplyAfterPreview`才会进入停写维护窗口：

1. 校验全部已解压源码文件SHA、配置、现有单API/私有网络、保护文件hash/inode及实际订单状态；创建0700唯一恢复目录，保留原env/compose/image。
2. 停API后再次查旧schema阻塞。使用现有只读backup身份做PG17 custom dump，恢复到无公网端口、独立volume/实际server identifier的PG17库，比对所有public表的完整行哈希和行数；源库变化即停止。
3. 从已验证stage构建API镜像。**生产DDL之前**先在刚恢复的隔离库中创建仅该隔离集群的三种专用角色，运行真实新迁移、快照CLI、再次独立恢复、preview/apply/verify；核对迁移不改原数据，并实际测试PG17角色权限、runtime伪造锁/维护标志不能写。源生产库仍为旧结构，隔离演练不通过不迁移生产。
4. 显式owner结构迁移，核对原金额/原字段行哈希不变；生成迁移后、业务替换前快照并实际独立恢复，真实CLI生成私有verified receipt和业务预览。
5. PowerShell显示该预览摘要、恢复目录和SHA；用户输入SHA末8位才传本次完整SHA到apply。拒绝/输入错误时API保持停止、备份全部保留；不假称已升级。
6. owner排他apply/verify之后，核对全部保留财务/历史/账号表哈希、金额和库存总计、每件原商品库存、管理员绑定和真实审计链。通过才保存旧源码并安装已校验源码、启动唯一新API并等健康；最后复制网页资源（入口最后替换、旧assets不删），不碰下载元数据或更新策略，nginx测试/reload后检查公开health。

`prepare`和`apply`通过host flock串行，确认阶段还核对工具revision一致。任何失败没有自动恢复生产dump、没有自动启动旧镜像碰新schema、没有删除容器/volume/备份。隔离演练成功只停临时PG容器，资源留存等待后续精确清理批准。`OPERATIONS_CLOUD_DEPLOYED_OK`仅在上述实际云端流程全部通过时输出，尚未由代理执行；手机/Win11/USB打印的实机验收和安装包发布仍是独立门禁。

本地本轮维护回归75项通过（15.07秒），Windows PowerShell 5.1真实包装器测试通过，覆盖确认拒绝/远端SHA篡改/不上传StageOnly；Docker/SSH/SCP为外部边界替身。本机无Docker/PG17，不能把这些单元测试冒称真实云端演练通过；实际演练被保留为上述生产DDL之前的运行时硬门禁。遵守不派代理要求，自行复查，未做独立第二人评审。

```powershell
Set-Location -LiteralPath 'F:\溪泉洗浴系统'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\invoke-operations-cutover.ps1' `
    -StageDirectory '/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54' `
    -ApplyAfterPreview
if ($LASTEXITCODE -ne 0) { throw '切换停止。保留恢复目录，把最后阶段及报错发送到本任务；不要运行旧update.sh或直接恢复生产。' }
```

维护期间不要让员工继续开牌/点单。若预览确认时主动退出，请保存输出中的PREVIEW_SHA256和job_path，后续使用同一工具`-Mode Apply -JobPath <实际路径> -PreviewSha256 <实际完整SHA>`显式继续；不得编造receipt、修改确认SHA、删除未结订单或把生产dump还原到生产库以绕过错误。
