# 0.5.5 人工盘点与 Excel 库存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户要求单代理、指定目录原位开发，不另建 worktree，不连接 ECS。

**Goal:** 三端下单不扣库存，通过受控 Excel 预览盘点、补齐新品资料及包装/基本单位成本换算管理库存。

**Architecture:** Flask 负责文件解析、匹配、成本与数量判断，原财务串行锁内事务应用、记录流水和审计。
Vue 页面只提交文件与明确确认，不自行覆盖库存。新字段和持久化待补队列采用加法迁移；部署复用已验证底层工具，不重放旧版本迁移。

**Tech Stack:** Vue 3 / Element Plus、Capacitor Android、Electron、Flask、SQLAlchemy、PostgreSQL 17；Excel OOXML 采用有界 ZIP/XML 读写，不增加在线安装依赖。

**Spec:** `docs/superpowers/specs/2026-10-13-desktop055-manual-inventory-excel-design.md`

## Global Constraints

- 桌面/网页 0.5.5；Win10/11 x86/x64，不做 Win7；安卓 1.2.12 / code19，发布前核对线上版本码更低。
- 减少 `(Q-N)/Q >= 0.25` 二次确认；数量是基本单位最终结存，不是入库增量。
- Excel 三可见列，隐藏标识；10 MiB / 1000 行 / 解压50 MiB，拒绝公式与外部链接。
- 新条目资料未补齐暂不正式入账；成本为空不修改，0有效；已有成本修改验证本人密码。
- 会员、金额、审计、历史流水、手牌绑定保持；业务重置不清库存。
- 原密钥/安卓证书，递增发布序号、完整公开字节校验；不代用户连接 ECS，不先删未归档资料。
- 文件编辑用 apply_patch；旧 0.5.4 冻结交付不伪装成新版本；测试数据仅隔离环境。

## Task 1：建立人工库存的新订单规则

**Files:** `server/app/stock_service.py`, `server/app/api/visits.py`, `server/app/receipt_cleanup_worker.py`；测试 `server/tests/test_manual_inventory055.py`。
**Interfaces:** 新订单耗用规范化永远为空；历史 `return_order_stock` 依据已有扣减证据返回。

- [ ] 写服务端真实 API 测试：service/product × single/batch/mobile，提交旧耗材字段仍不改变库存；零库存可售；撤销新订单不加库存。
  ```python
  response = client.post(path, headers=h, json=body)
  assert response.status_code == 201
  assert balance(client, h, stock_id)['stock_quantity'] == '800.000'
  ```
- [ ] 运行 `.venv\Scripts\python.exe -m pytest tests/test_manual_inventory055.py -q`，确认旧实现扣减导致失败。
- [ ] 在 `normalize_consumption` 和 `prepare_consumption` 停用新订单耗用；批量接口删除基于耗材的库存约束，兼容旧订单历史返库。
- [ ] 清理服务精确支持新 schema `20261013_manual_inventory_excel`，未知 schema 保持拒绝；测试新旧 schema。
- [ ] 运行新订单/旧返库针对性测试，更新旧测试表达新规则；提交本任务文件，不混入未跟踪历史恢复工具。

## Task 2：成本模型、待补资料和增量迁移

**Files:** `server/app/models.py`, `server/app/stock_cost_basis.py`, `server/app/serializers.py`, `server/app/api/inventory.py`；新增 `server/migrations/versions/20261013_manual_inventory_excel.py`；测试 `server/tests/test_stock_cost055.py`。
**Interfaces:** `stock_cost_values(master)` 返回 `package_cost`, `base_unit_cost`, `cost_basis`；`apply_stock_cost(master, body, employee)` 校验本人密码与精确换算。

- [ ] 写包装 120/200→基本0.6、基本0.6→包装120、不可整除、零/空值、首次与后续密码验证的真实 API 测试。
  ```python
  assert row['package_cost'] == '120.00'
  assert row['base_unit_cost'] == '0.600000'
  ```
- [ ] 跑测试确认当前 API 不支持新字段而失败。
- [ ] 新增参考成本计价口径字段（输入金额、base/package），派生值 Decimal 精确计算；兼容旧 `unit_cost`，历史采购成本不变。
- [ ] 新增待补库存持久化表，保存名称、原始数量/成本、来源摘要、操作者和状态；不猜单位。
- [ ] 增量迁移只添加字段/表和所需权限/保护，原业务行列摘要保持；新 schema 必须进入清理、owner备份和角色授权适配。
- [ ] 跑 API、SQLite 迁移及角色保护测试，提交。

## Task 3：有界 Excel 模板与解析

**Files:** 新增 `server/app/inventory_xlsx.py`；测试 `server/tests/test_inventory_xlsx055.py`。
**Interfaces:** `export_inventory_xlsx(rows) -> bytes`；`parse_inventory_xlsx(raw) -> list[dict]`，每条 `name,package_cost,quantity,stock_item_id,source_version,row_number`。

- [ ] 创建真实 ZIP/XML 文件测试，包含中文、数值0、空成本、隐藏ID、长名称、公式、重复列、外部链接、解压炸弹。
  ```python
  rows = parse_inventory_xlsx(export_inventory_xlsx(source))
  assert rows[0]['quantity'] == '800.000'
  assert rows[0]['package_cost'] == '120.00'
  ```
- [ ] 跑单文件测试看到缺失模块/行为失败。
- [ ] 用标准库 ZIP/XML 实现明确关系、共享字符串和内联字符串读取；拒绝 DTD/实体、公式、宏、external关系及危险路径；大小与行数在解析前后都限制。
- [ ] 导出冻结窗格、三可见列、隐藏ID/版本，明确基本数量/包装成本；名字作为字符串而非公式。
- [ ] 跑测试并用真实电子表格库读取导出以验证兼容，提交。

## Task 4：库存导入服务与受控 API

**Files:** 新增 `server/app/inventory_excel_service.py`, `server/app/api/inventory_excel.py`；修改 `server/app/__init__.py`；测试 `server/tests/test_inventory_excel055.py`。
**Interfaces:** GET `/inventory/excel/export`；POST `/inventory/excel/preview`, `/inventory/excel/apply`；GET `/inventory/excel/pending`；POST `/inventory/excel/pending/<id>/complete`, `/cancel`。

- [ ] 用真实client/auth/db测试唯一ID、无ID唯一名称、新待补、重复/归档/错误行、25%边界、成本密码、版本冲突、重试和事务回滚。
  ```python
  assert preview['rows'][0]['requires_consumption_confirmation'] is True
  assert client.post('/api/inventory/excel/apply', json=without_confirm, headers=h).status_code == 400
  ```
- [ ] 跑测试确认路由404和无保护的旧行为失败。
- [ ] SHA文件摘要+预览数据摘要与当前数据库版本生成确定预览；确认重复重算，在财务串行锁与事务内检查摘要、异常行确认及成本密码。
- [ ] 数量只调用 `change_balance(...,'adjust','Excel人工盘点',...)` 差额，无变化不写；待补完成新增 `StockItem` 和真实期初。
- [ ] 每批/每行有审计和幂等响应，提交后实时事件；保留原业务守卫/权限/经营期边界。
- [ ] 仅这个文件上传端点允许10MiB内容，其他端点保留原512KiB上限；测试越界。
- [ ] 跑服务端相关测试，提交。

## Task 5：三端直接下单与成本 UI

**Files:** `client/src/views/VisitView.vue`, `client/src/composables/useVisitOrdering.ts`, `client/src/views/InventoryView.vue`, `client/src/types.ts`；`mobile/src/views/VisitOrderView.vue`, `mobile/src/views/InventoryView.vue`, `mobile/src/types.ts`；库存domain新增换算函数。
**Interfaces:** `inventory_cost_basis:'base'|'package'`、`inventory_reference_cost`；下单直传空耗材兼容旧服务；库存界面显示包装与派生基本成本。

- [ ] 真实组件测试：点“加单”直接请求，无耗材对话框；商品仍支持多数量；手牌切换/套票替换/重试与打印不变。
- [ ] 运行 `npm.cmd exec vitest run src/views/VisitView.test.ts` 和手机对应测试，确认现行组件等待耗材导致失败。
- [ ] 移除耗材UI、读取依赖和选材状态；保留原幂等目标快照与套票确认。
- [ ] 成本表单双向联动，有明确基准，不把派生四舍五入作为输入；保留本人密码提示。
- [ ] 运行两个type-check与组件测试，提交。

## Task 6：三端导入预览与补齐资料界面

**Files:** 新增 `client/src/components/inventory/InventoryExcelPanel.vue`, `mobile/src/components/inventory/InventoryExcelPanel.vue` 及各自测试；修改两库存页面。
**Interfaces:** 导入面板调用Task4接口，emit `changed`触发库存刷新；待补入口红色带数量。

- [ ] 测试三列文件选择、export触发、错误行禁提交、25%确认、成本密码、冲突重预览、红色入口与补齐事务。
- [ ] 跑测试失败后实现面板，保持库存10条/右上分页，不放新增无关页面导航。
- [ ] 浏览器用Blob下载/文件选择；安卓用现有文件/分享机制保存，不伪称已保存或跳转网页替代APP更新。
- [ ] 三端断线禁写、权限撤销关闭对话框、成功后刷新；显示未知与0成本区分。
- [ ] 跑组件/类型检查及相关回归，提交。

## Task 7：真实库存快照与首次模板

**Files:** `发布 部署云端注意事项/采集0.5.5当前库存.ps1`；私有输出不入Git；模板生成器与xlsx验收。
**Interfaces:** 只读JSON包含ID/name/version/base_unit/package_unit/units_per_package/stock_quantity/unit_cost。

- [ ] 先测试脚本输出只含指定库存字段，PowerShell语法、UTF8与SSH quoting；不读取整份环境或inspect Env。
- [ ] 提供人类运行SSH的只读SQL采集脚本，自动保存目录；助手不执行网络。
- [ ] 用户提供云端snapshot后，按表格技能用Artifact Tool生成真实xlsx，并独立核对数量/换算/渲染。
- [ ] 未收到快照时交付应用导出能力但明确首次真实模板尚未生成，不能拿fixture冒充。

## Task 8：0.5.5 发布身份、迁移与保护

**Files:** 新 `desktop_055_{deploy,guard,pgproof}.py`, `invoke-desktop-055.ps1`, 新source/build/publication工具与测试；修改版本/日志；新delivery与注意事项。
**Interfaces:** schema predecessor `20261013_wristband_chip` → `20261013_manual_inventory_excel`，沿用真实恢复检查点、512/256MiB限制与HTTPS字节门禁。

- [ ] 写 schema精确前置、加法保护列、新表owner/runtime/backup授权、清理新schema与无旧readonly挂载的真实测试。
- [ ] 不直接对旧工具全局替换冒充新验证；沿用底层备份/财务障碍，明确新的表/字段和运行时切换。
- [ ] 更新client0.5.5/mobile1.2.12code19、精确两条日志、四通道及旧版兼容；签名序号由原签名历史和线上验签共同确定。
- [ ] 测试PG17隔离迁移、受认证API并发、两次心跳/保留审计，源码冻结后打包/哈希核验。
- [ ] 生成用户PowerShell入口：先只读验证云端，再部署、签名、桌面发布、原证书安卓构建/发布；失败精确续点、不无脑清理。

## Task 9：归档、全量验收与交付

**Files:** 0.5.5交付信息、最新版目录、归档manifest、`整理说明.md`与验收记录。

- [ ] 全量server/client/mobile与发布工具测试；冻结SOURCE后检查四安装包实际架构/版本/公钥。
- [ ] 人类签名与实机更新、云端操作未执行就分别标记待验收，不能声明上线。
- [ ] 用户已批准改用本机Git命令归档历史0.5.4及冗余候选，现有32MiB分片策略，远端完整SHA核验后精确删除；密钥/证书/备份/真实库存不公开。
- [ ] 更新本机目录保留清单；两处此前被工具拒绝删除的旧目录不得换工具绕过。
- [ ] 交付完整本机PowerShell、最新版包路径、测试结果及真实待完成项。

## 2026-10-13 本机执行记录（源码冻结前）

- Task 1–6：人工库存规则、成本模型、增量迁移、受控Excel接口及三端页面已实现；旧实际扣减订单返库仍保留。
- Task 7：用户提供真实库存快照，58项数量逐条核验；首份真实盘点表已生成，17项未知单位保留待补，不猜测入账。数据文件只保存在私有目录。
- Task 8：0.5.5四桌面通道、安卓1.2.12/code19、原密钥签名与云端PG17隔离证明入口已准备。助手未连接ECS，真实云端证明、签名及实机覆盖安装待用户执行。
- Task 9：桌面页面352项、手机218项及发布工具针对性检查通过；服务端全量复核正在运行。旧0.5.4共498文件按32MiB分片、4批去重上传，远端完整字节证明未完成前不删除原文件。
- “前台”即cashier仍拥有手牌ID录入页面及绑定接口权限，7项权限测试通过；本次未扩大其他岗位的绑定权限。

以上为冻结前记录，不替代构建交付元数据、最终测试报告或云端completed.json；交付与归档完成状态见根目录整理说明及私有证据。
