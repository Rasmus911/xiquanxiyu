# 溪泉营业升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 不自动派发子代理；执行方式由用户选择。

**Goal:** 修复员工授权及联动点单，落地新价目表、套票、001–100 手牌，交付一致的三端更新和安全的用户自执行部署流程。

**Architecture:** 沿用单 ECS API / PostgreSQL。权限、点单、计费和发布分别有独立实现计划和测试接口，按依赖顺序合并；数据替换通过有备份、有预览、有排他锁的维护 CLI，而非应用启动副作用。

**Tech Stack:** Vue 3、Element Plus、Flask、SQLAlchemy、Alembic、PostgreSQL 17、Electron、Capacitor Android、pytest、Vitest、Node test runner、PowerShell。

**Spec:** [已确认设计](F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-04-operations-permissions-catalog-upgrade-design.md)

## Global Constraints

- 工作目录 `F:\溪泉洗浴系统`；保留所有既有用户文件，不使用 reset/checkout 清理工作区。
- 共享云 API `https://api.pqxqxy.xyz/api`，ECS `39.96.217.210`，远端根目录 `/opt/xiquan/xiquan`。
- 代理不执行 SSH 上传、云端业务写入、迁移或删除；用户运行最后提供的 PowerShell。
- 男浴 `001–050`，女浴 `051–100`，各 50 个；号码以字符串保存。
- 正式价目表 42 项；套票 A–G 总价分别为 45/48/55/78/108/188/218 元，不重复计费。
- 收银员主页面为手牌、会员、小票补打；库管库存；普通搓澡师/三层服务员已激活手牌点单。辅助登录/退出/连接设置不扩权。
- 既有最高管理员 UUID 绑定保留；仅绑定店主具有重置/归档权力。新增 role=admin 不自动获得最高权限。
- 新耗材库存为 0，已有库存及饮品保留；旧服务和旧手牌逻辑停用，历史记录保留。
- 原更新信任根、appId、终端配置不替换；签名密码由用户隐藏输入。
- 用户执行中缩小范围：本次仅构建win11-x64，Electron44.5.1；保留其它目标的历史配置、更新通道和回滚包，不再构建其余五包。
- 增补验收：于在跃、李丽娜、于景辉既有绑定UUID的手机登录/通道关闭及最高手机能力；未知/未绑定同名账号仍拒绝，不改账户密码。
- 目标桌面 0.4.3、Android 1.2.2 / versionCode 9；若实际已发布更高版本则递增，禁止复用签名发布序号。
- 每个代码步骤先红测再实现再绿测。测试只使用隔离 SQLite/测试 PostgreSQL，禁止读取生产 `.env` 或发送真实短信。
- Git 只加入明确列出的安全源码；凭据扫描输出文件位置/规则，不输出敏感值。不创建远程仓库或推送。

## 执行顺序和计划边界

- [x] 先执行 [发布维护计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-release.md) R1：源码安全基线。8项安全检查器测试及434个白名单文件扫描通过（2026-10-04）。
- [x] 执行 [账号与权限计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-permissions.md) A1–A5，得到可授权普通员工、动作级错误和端到端角色边界。已本地回归；云端绑定和实机仍待部署验收。
- [x] 执行 [点单体验计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-ordering.md) B1–B4，得到安全切换、顶部提交、混排和云端排序。已完成本地回归，触屏实机与PG并发待部署前验收。
- [x] 执行 [目录和计费计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-billing.md) C1–C7，得到正式价目表、维护迁移、票种和套餐。本地414项后端、127项Vue/70项Electron、111项手机回归；PG17、真实恢复及实机门禁仍待R2/R3验收。
- [ ] 返回发布维护计划 R2–R4，完成回归、包校验、用户签名构建命令、部署与清理预览。
- [x] 用户选择2：当前会话内执行，不使用子代理。源码升级、安装包和云端部署分别验收，不混称完成。

四份计划各自能够产生可独立测试的交付件，但最终正式发布必须全部完成。B 在原服务/商品目录上可独立验收；C 增加 package 类型时扩展 B 的同一排序契约，不另建排序系统。

## 共享接口总览

| 接口/数据 | 生产者 | 消费者 |
| --- | --- | --- |
| Employee.allowed_channels / deleted_at | A1 | A2、A3、A5 |
| permission_scope + business_state.ui_pages / capabilities（含checkout_write） | A1、A2 | A4、A5、B、C |
| ordering_scope.can_read_visit / can_sell_catalog | A3 | 桌面/mobile API、B、C |
| CatalogLayout {revision, ids} | B3 | B4、C1/C3 |
| VisitDraftBook / request-gated visit loader | B1 | B2、C6 |
| CatalogItem.package_definition / reference_code | C1、C2 | C3–C7 |
| OrderItem.covered_quantity / package_order_item_id / package_snapshot | C2、C5 | C6、C7、原结账/打印/报表 |
| operations-upgrade preview / apply / verify | C3 | R3 用户部署 |
| source security report / release-manifest.json | R1、R2 | Git 基线、部署清单、R4 清理 |

## 统一验证命令

所有命令从项目根目录运行；pytest 禁止 dotenv 自动加载：

```powershell
Set-Location -LiteralPath 'F:\溪泉洗浴系统'
$env:PYTHON_DOTENV_DISABLED = '1'
& '.\server\.venv\Scripts\python.exe' -m pytest '.\server\tests' -q
if ($LASTEXITCODE -ne 0) { throw '后端回归失败，停止发布' }
Push-Location -LiteralPath '.\client'
try {
    npm.cmd run type-check
    if ($LASTEXITCODE -ne 0) { throw '桌面类型检查失败' }
    npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw '桌面回归失败' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '桌面构建失败' }
} finally { Pop-Location }
Push-Location -LiteralPath '.\mobile'
try {
    npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw '手机回归失败' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '手机构建失败' }
} finally { Pop-Location }
node.exe --test '.\scripts\lib\desktop-release.node-test.cjs' '.\scripts\lib\windows-publish.node-test.cjs' '.\scripts\lib\windows-delivery.node-test.cjs'
if ($LASTEXITCODE -ne 0) { throw '发布安全回归失败' }
```

后端 TestConfig 当前位于 server/app/config.py，内存 SQLite 且 AUTO_CREATE_DB=False；迁移、排他锁及恢复测试另建 tmp_path 文件库。PostgreSQL 触发器/并发必须在独立测试实例验证，不能用 SQLite 通过代替 PG 通过。

## 完成前检查

设计验收逐项映射（20个任务均有红/绿测和独立提交）：

| 设计验收号 | 实现任务 | 验证重点 |
| --- | --- | --- |
| 1–2 | A1、A2 | 员工授权/启用，目标会话撤销不误踢操作者 |
| 3 | A2、A4 | 逻辑删除、用户名保留、受保护UUID、审计证据 |
| 4–5 | A3–A5 | 岗位页面/按钮/API、跨浴区联动和商品范围 |
| 6 | B1 | 路由复用、乱序响应、提交快照、返回状态 |
| 7 | B2 | 混排与右上提交、数量、窄屏及输入快捷键 |
| 8 | B3、B4 | 原子排列版本、全量ID、触屏/鼠标/键盘 |
| 9 | C1–C3 | 42条正式定义、旧服务退役、原库存与种子 |
| 10 | C4 | 15/10元逐人票种，员工不得改票 |
| 11–12 | C5–C7 | 套餐包含净额、幂等、库存、小票与报表 |
| 13 | C2、C3、R3 | 阻塞预检、001–050/051–100、历史保留和恢复 |
| 14 | A5、B、C7、R2–R3 | 三端实时通知/补拉、最高管理能力不回退 |
| 15 | R1、R4 | 安全Git基线，精确清单与可恢复归档 |
| 16 | A5、R2、R3 | Win11-x64/原证书APK/更新信任/USB打印及三位管理员手机登录 |

- [ ] 设计验收 1–16 均有对应自动测试或注明用户实机步骤。
- [ ] 记录各任务红/绿测试命令、退出码和 Git commit；不存在未验证“已修复”声明。
- [ ] Win11-x64、Android原证书覆盖安装、XP-58/USB003打印、断线重连和三位绑定管理员手机登录实机核实，未核实如实列出。
- [ ] 安装包目录、ZIP、版本、SHA256、签名状态与清单一致；无 SOURCE-WEB 文件伪装成完整桌面/APK 发布。
- [ ] 本地开发完成、签名待用户执行、云端待用户部署、ECS 清理待精确路径确认，分别报告，不混为“全部上线”。
