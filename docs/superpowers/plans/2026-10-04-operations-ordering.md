# 联动点单与混排布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 联动切换不中途串单，提交位于选择区域右上方，服务/商品可混排且云端同步排列。

**Architecture:** 请求序号与会话 generation 双重隔离；草稿按 visit UUID 保存。选择和排列是互斥模式；排序通过完整 ID 集合、布局版本和原子事务提交，不修改营业选择草稿。

**Tech Stack:** Vue 3、TypeScript、Vitest、Flask/SQLAlchemy、Pointer Events，复用已有依赖，不额外引入拖拽 UI 库。

**Spec:** [设计第 5 节](F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-04-operations-permissions-catalog-upgrade-design.md)

## Global Constraints

继承[总计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-upgrade.md)全部约束；前置 A 的 permission_scope/ui_pages/capabilities 与对象级范围。普通员工不能保存排列；服务和商品混排不改变库存业务类型。Chrome 108 可用，触屏拖拽只能在手柄启动。

## 文件责任

- `F:/溪泉洗浴系统/client/src/domain/orders/visit-drafts.ts`：草稿读写及提交不可变快照。
- `F:/溪泉洗浴系统/client/src/domain/orders/load-gate.ts`：最后一次请求可写回判定。
- `F:/溪泉洗浴系统/client/src/composables/useVisitOrdering.ts`：路由、HTTP、草稿和业务 generation 的组合，不包含页面标记。
- `F:/溪泉洗浴系统/server/app/catalog_layout.py`：全局目录布局版本、全量 ID 验证、原子排序及审计。
- 双前端 `domain/catalog/layout.ts`：纯排序移动函数；各自测试同一契约，不从另一个前端的 node_modules 偷用依赖。

### B1：联动路由、请求竞争和提交归属

**Files:** 新建上述 drafts/load-gate/useVisitOrdering 文件及对应 .test.ts、client/src/domain/wristbands/return-state.ts / .test.ts、server/tests/test_order_target_version.py；修改 client/src/views/VisitView.vue、DashboardView.vue、components/orders/PartyTabs.vue、mobile/src/stores/business.ts、mobile/src/views/VisitOrderView.vue、server/app/api/visits.py / mobile.py；新增 views/VisitView.test.ts，扩展 mobile/src/stores/business.test.ts。

**Interfaces:**

```ts
type Quantities = Record<string, number>
interface VisitLoadTicket { visitId: string; sequence: number }
interface SubmissionSnapshot { visitId: string; visitVersion: number; quantities: Readonly<Quantities>; units: number; kinds: number }
interface VisitLoadGate {
  begin(id: string): VisitLoadTicket
  current(ticket: VisitLoadTicket): boolean
  reset(): void
}
interface VisitDraftMethods {
  read(id: string): Quantities
  replace(id: string, values: Quantities): void
  clear(id?: string): void
  capture(id: string, version: number): SubmissionSnapshot
}
```

`createVisitLoadGate():VisitLoadGate` 与class `VisitDraftBook implements VisitDraftMethods` 为本任务实际实现；`useVisitOrdering()` 返回loading/error/currentVisit（Ref<Visit|null>）、drafts、load(visitId:string):Promise<void>、submitSnapshot(target:SubmissionSnapshot):Promise<void>。submitSnapshot内部拿/清pendingRequestKey，成功返回void，失败抛HTTP错误；调用者负责generation验证和清对应草稿。沿用现有business/state导出的businessGeneration/assertCurrent/onBusinessSessionClear，runtime来自现有runtime adapter，不另造全局身份状态。

返回界面契约：`saveDashboardReturn(state:{area:'all'|'male'|'female',keyword:string,scrollTop:number}):void`、`readDashboardReturn():该state|null`、`clearDashboardReturn():void` 定义于return-state.ts；仅当前会话内存状态，登出/period变更清除，不落持久存储或保存用户账单。

- [ ] **1. 红测草稿、异步切换。**

```ts
it('late A cannot overwrite selected B', () => {
  const gate = createVisitLoadGate()
  const a = gate.begin('visit-a')
  const b = gate.begin('visit-b')
  expect(gate.current(a)).toBe(false)
  expect(gate.current(b)).toBe(true)
})
it('capture belongs to its visit even when UI moves', () => {
  const drafts = new VisitDraftBook()
  drafts.replace('visit-a', {soap: 2})
  const submission = drafts.capture('visit-a', 3)
  drafts.replace('visit-b', {water: 3})
  drafts.replace('visit-a', {soap: 9})
  expect(submission.visitId).toBe('visit-a')
  expect(submission.visitVersion).toBe(3)
  expect(submission.quantities).toEqual({soap: 2})
  expect(drafts.read('visit-b')).toEqual({water: 3})
})
it('return preserves area and scroll but not beyond logout', () => {
  saveDashboardReturn({area:'female',keyword:'051',scrollTop:640})
  expect(readDashboardReturn()?.scrollTop).toBe(640)
  clearDashboardReturn()
  expect(readDashboardReturn()).toBeNull()
})
```

视图测试用真实 memory router 与 deferred Axios adapter：导航 A→B→C，按 C/B/A 顺序完成请求，断言只显示 C。延迟 runtime.setBusinessBusy 时导航 B，POST URL/数量必须仍为点击时 A；返回成功只清 A 草稿。切换后结账 returnTo 仍正确。Session generation 清理后旧成功/失败均不能复填或清新草稿。
- [ ] **2. 运行红测。** client `npx.cmd vitest run src/domain/orders/visit-drafts.test.ts src/domain/orders/load-gate.test.ts src/views/VisitView.test.ts`；mobile `npx.cmd vitest run src/stores/business.test.ts`。
- [ ] **3. 实现纯单元与组合。** VisitDraftBook 读写深复制数值字典；capture 在任何 await 前固定 visit/quantities/version。gate 用递增 sequence+visitId；会话清理订阅使 drafts.clear()/gate.reset()。`watch(() => route.params.id, load, {immediate:true})` 代替仅 onMounted 加载；实时刷新同样携带 request ticket。只更新当前序号的 loading/error/详情。手牌标签按当前路由 ID 而不是旧 response 立即高亮。当前详情UUID还未匹配新route时禁用提交，不能把旧详情version与新route拼成快照。

```ts
if (!currentVisit.value || currentVisit.value.id !== String(route.params.id)) return
const target = drafts.capture(currentVisit.value.id, currentVisit.value.version)
const generation = businessGeneration.capture()
const releaseBusy = await runtime.setBusinessBusy('正在提交加单')
try {
  assertCurrent(generation)
  await submitSnapshot(target)
  assertCurrent(generation)
  drafts.clear(target.visitId)
} finally {
  await releaseBusy()
}
```

submitSnapshot 在 useVisitOrdering 创建：使用现有 pendingRequestKey/orderFingerprint，POST `/visits/${target.visitId}/items/batch` body携带version=target.visitVersion；失败保留同一幂等键和目标草稿，成功才清 key。fingerprint包含UUID/version/商品ID/数量，网络重试复用原完整payload，不用新version重新包装旧key。服务端幂等命中先返回原结果；新请求加行锁后比对传入version，过期409且无库存/订单写入。兼容旧合法客户端缺version时仍保留原行锁和当前状态检查，不能因缺字段绕过role/period/幂等。该方法不再次读取route或当前selection。目标已结清通知时仅清相应visit，不把同号新visit当成原对象。Dashboard离开前存area/search/scroll，返回mounted恢复筛选、await nextTick后恢复滚动；辅助状态在onBusinessSessionClear清理。
- [ ] **4. 绿测与回归。** 跑上述及 pending-key、order-selection、business operations 和 realtime 原测试。页面去掉覆盖 PartyTabs 的 v-loading，改内容区域局部 loading。手机 selectVisit 按 UUID 缓存并在结清/登出清理；保留原 bootstrap request sequence。
- [ ] **5. 提交。** `fix: isolate linked wristband drafts requests and submission targets`。

### B2：混合目录与顶部提交

**Files:** 修改 client/src/components/orders/CatalogPicker.vue、OrderCart.vue、views/VisitView.vue；mobile/src/components/orders/CatalogTabs.vue、MobileCatalogPicker.vue、OrderSummaryBar.vue、views/VisitOrderView.vue；新建双端 domain/catalog/filter.ts / .test.ts、client/src/components/orders/CatalogPicker.test.ts。

**Interfaces:** `CatalogFilterKind='all'|'service'|'product'`；`visibleCatalog(items, {kind,category,keyword})` 返回按现有 sort_order 稳定排列的可售子序列。C6 再添加 package 属于 service filter 的正式扩展。

- [ ] **1. 红测混排和动作位置。**

```ts
it('all can place a service beside a counted product', () => {
  const items = [
    {id:'mud', kind:'product', name:'搓泥宝', category:'洗浴', is_active:true, sort_order:20},
    {id:'scrub', kind:'service', name:'搓澡', category:'洗浴', is_active:true, sort_order:10},
  ]
  expect(visibleCatalog(items, {kind:'all', category:'', keyword:''}).map(x=>x.id))
    .toEqual(['scrub','mud'])
})
```

真实 picker mount 检查默认 all、商品 stepper 不冒泡重复选择、缺货普通模式不选中、service一次、分类切换不清营业草稿。VisitView 通过 `[data-testid="quick-order-header"] [data-testid="submit-order"]` 定位按钮；无选择/提交中/离线禁用。手机上下摘要来自同一 units/kinds/amount 状态，仅触发一次 submit。keyboard 测试在搜索输入框 Enter 不误提交、Esc 关闭弹窗。
- [ ] **2. 运行。** client 对两个 domain/filter 和组件/视图测试；mobile `npx.cmd vitest run src/domain/catalog/filter.test.ts src/order-selection.test.ts`。
- [ ] **3. 实现。** 默认全部+服务+商品三类；先根据 kind 范围（当前 service/product）及授权数据排除 ticket/compensation，再排序和筛选。分类列表基于当前 kind 子序列。OrderCart 添加 `compact` 展示模式并移入标题右侧；只保留一个主提交动作源。header grid 为文本/统计/按钮，窄屏 wrap，无固定绝对坐标；输入数量控件停止 click 冒泡。mobile 同样顶部操作，底栏若保留只镜像同一 action/busy。

```ts
return items.filter(item => item.is_active &&
  (filter.kind === 'all' || item.kind === filter.kind) &&
  (!filter.category || item.category === filter.category) &&
  (!filter.keyword.trim() || item.name.includes(filter.keyword.trim())))
  .sort((a,b) => a.sort_order-b.sort_order || a.id.localeCompare(b.id))
```

实际输入类型为双端 CatalogItem 接口；不是给 product 更改 kind。禁用针对操作按钮而非布局编辑卡片本身，缺货商品仍可参与管理员排列。
- [ ] **4. 绿测和构建。** 双端测试及 type-check/build；1366/1024 桌面宽度和 360/390 手机宽度检查 header 按钮不溢出。Win7 runtime 以现有兼容脚本实查，不增加 CSS :has/subgrid 等新运行时依赖。
- [ ] **5. 提交。** `feat: add mixed quick ordering and top aligned submit controls`。

### B3：完整目录原子排序 API

**Files:** 新建 server/app/catalog_layout.py、financial_lock.py、server/tests/test_catalog_layout.py、test_financial_lock.py；修改 server/app/api/catalog.py、access_policy.py、employee_access.py、serializers.py；SystemSetting 使用现有 schema，无新增表。C5扩展本任务financial lock到其它金额写API，不重复创建另一个锁。

**Interfaces:** `CatalogLayout={revision:int, ids:list[str]}`；GET `/api/catalog/layout`，PUT 同路径 body `{revision,ids}`；权限 `catalog:layout`，仅绑定最高管理员对应允许入口。mobile 最高管理员 scope 加该权限，不添加 catalog:write，从而不能顺带改价。

本任务产生 `serialized_financial_write` 装饰器：在已验证身份权限之后、业务行锁之前通过db.session拿PostgreSQL transaction advisory key713829418，commit/rollback自动释放；SQLite测试验证调用顺序但不宣称PG互锁证明。catalog新增/停用/调价和layout PUT都先拿同一锁，防止“layout setting→catalog”与“catalog→layout setting”反向行锁死锁；C5后续复用同一接口/常量。

- [ ] **1. 红测。** owner GET layout 返回所有 active service/product ID；PUT 反转全量 IDs 后目录返回相同顺序；再次带旧 revision409。参数化重复 ID、遗漏/外部ID、ticketID、非整数revision、无权限cashier/floor；全部失败无部分 sort_order 变化。库存0的商品也可排序。mobile最高管理账号成功，manager虽有catalog:write仍无layout权限。

```python
def test_layout_compare_and_swap(client, strict_owner_session):
    h = strict_owner_session['headers']
    before = client.get('/api/catalog/layout', headers=h).get_json()['data']
    payload = {'revision':before['revision'], 'ids':list(reversed(before['ids']))}
    saved = client.put('/api/catalog/layout', headers=h, json=payload)
    assert saved.status_code == 200
    assert saved.get_json()['data']['ids'] == payload['ids']
    assert client.put('/api/catalog/layout', headers=h, json=payload).status_code == 409
```

- [ ] **2. 运行。** `python -m pytest server/tests/test_catalog_layout.py -q`，确认无路由或功能缺失的红测。
- [ ] **3. 实现。** 保存 SystemSetting key=`catalog_layout`，value 只做布局标识，version 作为 revision。懒初始化受事务保护，避免两个并发GET插入唯一键失败；可在种子中只创建该setting但不自动覆盖。PUT 先锁 setting，再读取并锁所有 active quick-order catalog（按 UUID），检查集合精确相等且revision匹配，再赋 `sort_order=(index+1)*10`，setting.version++，审计 before/after，commit 后 emit catalog.changed。

```python
@bp.put('/layout')
@require_permission('catalog:layout')
@serialized_financial_write
def save_layout():
    body = request.get_json(silent=True) or {}
    result = save_catalog_layout(db.session, current_employee(), body.get('revision'), body.get('ids'))
    db.session.commit()
    emit_business_event('catalog.changed', {'reason':'layout'})
    return success(result)
```

`save_catalog_layout(session:Session,employee:Employee,revision:object,ids:object)->dict` 在catalog_layout.py实现，锁/集合/审计按下述检查，不独立commit。

```python
if type(revision) is not int or revision != setting.version:
    raise ApiError('排列已改变，请刷新', 409, 'CATALOG_LAYOUT_CONFLICT')
if (not isinstance(ids, list) or any(not isinstance(x, str) for x in ids)
        or len(ids) != len(set(ids)) or set(ids) != set(expected_ids)):
    raise ApiError('排列集合不完整，请刷新', 409, 'CATALOG_LAYOUT_CONFLICT')
```

所有新增/停用 quick items 时同事务提升 layout version；后续 C3 替换也调用同一方法 `touch_catalog_layout(session)`。函数在本任务定义：锁setting、version++、不commit，供调用者原子commit。未知scope事件不能直接广播详情。
- [ ] **4. 绿测。** 增加并发独立 PG 测试，两次旧revision仅一成功，失败事务无写；SQLite通过单元验证，不假装覆盖PG并发。跑catalog/pricing原业务测试。
- [ ] **5. 提交。** `feat: add audited versioned catalog layout persistence`。

### B4：触屏/鼠标拖拽与键盘备用操作

**Files:** 新建双端 domain/catalog/layout.ts / .test.ts、composables/useCatalogLayout.ts / .test.ts；修改 CatalogPicker.vue、MobileCatalogPicker.vue、VisitView.vue、VisitOrderView.vue；扩展相关组件测试。

**Interfaces:** `moveBefore(ids:string[], source:string, target:string):string[]`；`useCatalogLayout` 返回 `{editing,ids,revision,busy,begin,cancel,move,save}`，GET/PUT 消费 B3，取消不写服务器。

- [ ] **1. 红测。**

```ts
it('moves mud beside scrub without mutating original', () => {
  const ids = ['scrub','towel','mud']
  expect(moveBefore(ids,'mud','towel')).toEqual(['scrub','mud','towel'])
  expect(ids).toEqual(['scrub','towel','mud'])
  expect(moveBefore(ids,'missing','towel')).toEqual(ids)
})
```

组件事件测试普通模式 pointer/click 只选项目；进入编辑清搜索/分类并显示完整all；编辑中的drag/up-down只改ids不改quantities；cancel不PUT；save409保留编辑并提示刷新；忙时不能重复save；员工无编辑按钮。触屏pointerup结束状态后click不能额外售出。
- [ ] **2. 运行。** 双端 npx vitest 对 layout/filter/composable 和组件用例，预期缺模块失败。
- [ ] **3. 实现。** 从原id列表复制draft；drag handle 设置 touch-action:none，仅手柄捕获pointer；pointerup通过 elementFromPoint 找 data-catalog-id，调用moveBefore，pointercancel清拖动状态；其他区域仍正常滚动。键盘可聚焦上移/下移按钮使用同一move方法。普通点击在editing时不emit select，编辑返回营业保持草稿。

```ts
function moveBefore(ids: string[], source: string, target: string): string[] {
  if (source === target || !ids.includes(source) || !ids.includes(target)) return [...ids]
  const next = ids.filter(id => id !== source)
  next.splice(next.indexOf(target), 0, source)
  return next
}
```

修改顺序只保存一次PUT；响应成功用返回revision/ids刷新，后台目录成员变化须退出当前编辑并要求重新载入全量。目录 realtime refresh 不覆盖正编辑的 draft；只提示版本已改变。新增B3函数touch版本的事件仍对有权限端刷新。
- [ ] **4. 绿测和交互验收。** 完成上述双端构建，记录“搓澡→搓泥宝相邻”鼠标、触屏、键盘三种操作结果；未有手机实机时只记录DOM自动测试，实机项留在R2清单，不宣称已测。
- [ ] **5. 提交。** `feat: add accessible administrator catalog rearrangement across clients`，A/B在旧目录下可独立验收，随后交C。
