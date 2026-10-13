# 0.5.2 实体卡结账修复发布计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户要求单代理执行，在指定的本地项目中交付；不使用子代理，不连接 ECS。步骤用 checkbox 跟踪。

**Goal:** 把已经修复的实体卡结账错误作为 0.5.2 补丁交付，用原签名信任和原更新通道让旧客户端下载覆盖安装。

**Architecture:** 只更新桌面页面和版本元数据。四种 Win10/Win11 安装包沿用应用 ID、公开发布公钥及更新来源；复用已有签名、暂存和通道激活代码，不重新部署 API、不迁移数据库。发布密码由用户在本机隐藏输入，在线序号从四个经过原公钥验签的现行策略计算，不猜测序号。

**Tech Stack:** Vue 3、Electron、electron-builder、Node.js、PowerShell、Ed25519。

**Spec:** `docs/bugfixes/2026-10-12-physical-card-checkout.md` 及用户已确认的“编号 0.5.2，签名并发布到更新通道”要求。

## Global Constraints

- 桌面版本 0.5.2；安卓仍为 1.2.9，不改手机和网页、API 或数据库。
- 目标只有 win10-x86、win10-x64、win11-x86、win11-x64。
- 原公开发布 key ID 为 b26477a9ed540ad0，不新建密钥。
- 不覆盖已经发布的 0.5.1 安装包或已签名策略；新建构建目录。
- 原地处理当前用户指定的 `F:\溪泉洗浴系统`，保留其他未提交修改。
- 代理只完成本地构建、回归和交付；签名密码及云端发布由用户执行脚本。

### Task 1: 修复版本与更新兼容性

**Files:**
- Modify: `client/package.json`、`client/package-lock.json`、`client/src/update/history-data.json`
- Test: `client/src/update/release-history.test.ts`、`client/electron/updater.node-test.cjs`
- 保持已有修复：`client/src/components/members/CardScanDialog.vue`

- [x] 添加日志用例，要求最新行是 0.5.2、日志为“修复实体卡结账时会员查询一闪而过、无法消费的问题”、状态待发布；运行 `node node_modules/vitest/vitest.mjs run src/update/release-history.test.ts`，确认旧日志失败。
- [x] 把 client 包和锁文件两处根版本改为 0.5.2，追加待发布日志，调整历史测试按版本取条目，运行上述命令通过。
- [x] 添加原 updater 适配器用例：0.4.4 至 0.5.1 在四个匹配的已签名通道下载 0.5.2；运行 `node --test electron/updater.node-test.cjs` 验证。
- [x] 执行 `npm.cmd test`，确认刷卡关闭动画回归及其他前端、桌面测试通过。

### Task 2: 构建与安全发布交付

**Files:**
- Create: `scripts/publish-desktop-052.ps1`
- Create: `最新版安装包-实体卡结账修复-0.5.2/01-签名并发布修复更新.ps1`
- Create: 交付目录中的 README、校验清单和交付 JSON。
- Reuse: `scripts/build-windows-release.ps1`、`scripts/sign-windows-release.ps1`、`scripts/publish-windows-release.ps1`、`scripts/lib/desktop-045.cjs`、`scripts/lib/windows-public-recovery.cjs`

- [x] 使用原 public key 和已校验的离线 Electron 档案构建四包；在同一个 PowerShell 进程传 `-Targets @('win10-x86','win10-x64','win11-x86','win11-x64')`，避免外层 `-File` 把 CSV 当成单个数组值。构建参数版本 0.5.2，新 BuildId，不复用 0.5.1 输出。
- [x] 独立验证四包架构、版本、公钥以及 ASAR 中的修复代码，与本地 production renderer 比较字节。
- [x] 发布脚本先校验本地交付哈希和候选包，再读取并验签在线序号；按旧 minimumVersion 分组，调用已有隐藏密码签名函数。已经签名的包只校验并继续，不覆盖签名。
- [x] 发布使用原四通道及 legacy bridge，并保留现有手机/web 策略。公开校验超时只能运行只读复核，不能重新签名、迁移或重建。不得在未成功验证前输出“发布成功”。
- [x] PowerShell AST 解析、`-PreflightOnly` 无联网校验、所有本地包哈希检查通过；交付一条 PowerShell 指令。明确记录尚未签名/尚未云端发布状态。

无需提交无关文件、访问生产数据库、修改价格或会员余额。后续可在用户发布成功后，对一笔正常订单使用实际 D5 读卡器验收。

## 本地交付验收（2026-10-12）

- `npm.cmd test`：322 项前端测试、87 项 Electron/构建测试通过。
- 发布计划及只读公开校验测试：11 项通过。
- 四个 0.5.2 包的版本、架构、原公钥、安装包 SHA256 与 ASAR 中刷卡关闭保护均已核对。
- 发布脚本 PowerShell AST 解析通过；交付入口 `-PreflightOnly` 成功，没有联网、签名、上传或数据库变更。
- 交付目录：`F:\溪泉洗浴系统\最新版安装包-实体卡结账修复-0.5.2`。

后续仍待完成（需要用户本机执行）：

- [ ] 隐藏输入原发布密钥密码，签名并上传；看到 `DESKTOP052_PUBLICATION_VERIFIED` 确认公开更新通道验证成功。
- [ ] 旧版通过“检查更新”下载安装 0.5.2，并用实际 D5 读卡器验收一次正常结账。
