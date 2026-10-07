# 员工授权与岗位边界 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增/启用员工不误退出管理员，实现逻辑删除与严格岗位隔离。

**Architecture:** 既有最高管理员继续走 UUID 入口策略；普通员工采用持久化入口授权和服务端角色模板。统一服务端页面能力和对象级点单范围，HTTP 和 Socket 均验证当前会话。

**Tech Stack:** Flask、SQLAlchemy/Alembic、JWT/Socket.IO、Vue/Pinia、pytest、Vitest。

**Spec:** [设计第 3–4 节](F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-04-operations-permissions-catalog-upgrade-design.md)

## Global Constraints

继承[总计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-upgrade.md)全部约束。前置 R1 安全源码基线。既有管理员保留，不改密码，不按姓名授权；仅普通员工操作不得改变全局 policy_version。用户测试库和云端库不用于测试。

## 文件责任

- `F:/溪泉洗浴系统/server/app/employee_access.py`：入口校验、页面能力、受保护管理员识别，唯一岗位定义入口。
- `F:/溪泉洗浴系统/server/app/ordering_scope.py`：浴区、已激活状态、可售范围的对象级检查。
- `F:/溪泉洗浴系统/server/app/api/employees.py`：创建/修改/逻辑删除事务和审计，不负责计算菜单。
- `F:/溪泉洗浴系统/client/src/navigation/access.ts`：根据服务端 ui_pages 判定路由/落点；不推测最高权限。
- `F:/溪泉洗浴系统/server/tests/conftest.py`：新增隔离权限 fixture，不改变已有 admin_session 的 legacy 模式。

### A1：入口字段、固定角色模板和测试 fixture

**Files:** 修改 server/app/models.py、auth_service.py、access_policy.py、serializers.py、business_period.py、api/auth.py、api/business.py、tests/conftest.py；新建 server/app/employee_access.py、server/migrations/versions/20261004_employee_entries.py、server/tests/test_employee_entries.py。

**Interfaces:**

函数契约（由本任务实现，不是空函数占位）：

- DEFAULT_CHANNELS 类型 `dict[str, tuple[str, ...]]`，cashier=(desktop,web)，inventory/staff=(desktop,web,mobile)。
- `validate_employee_channels(role: str, channels: object) -> list[str]`：规范顺序与岗位入口交集，不合法抛 ApiError。
- `is_protected_employee(employee: Employee) -> bool`：owner/admin-list/mobile-list UUID身份。
- `session_ui(employee: Employee, channel: str, permissions: set[str]) -> dict`：输出 `{ui_pages:list[str],capabilities:dict[str,bool]}`；pages为 wristbands,members,print-jobs,catalog,inventory,reports,audit,employees,settings。
- capabilities固定键 `visit_open`、`visit_manage`、`visit_order`、`checkout_write`、`member_write`、`receipt_reprint`、`inventory_write`、`catalog_layout`、`package_write`（C6接入）；未知键不得默认true，owner_reset仍用原独立绑定字段。
- `business_state_data(employee=None, channel: str | None=None) -> dict` 在现有状态上附 ui_pages/capabilities；登录时传服务器验证过的channel，已登录/state/refresh使用已验证JWT的client_channel，不采信查询参数/未验证header。

这些函数在本任务创建，后续 A2/A4/A5 消费。`is_protected_employee` 用于禁止普通编辑/删除，不等同于授予桌面入口；登录继续保持既有入口名单，手机专属绑定不会因模板而变成桌面通配权限。

- [ ] **1. 添加 fixture 和红测。** conftest 中增加以下 fixture；真实数据全部在 TestConfig 中：

```python
@pytest.fixture()
def strict_owner_session(app, client):
    from app.auth_service import hash_password
    from app.models import AccessPolicyModel, BusinessStateModel, Employee, Terminal
    app.config['ACCESS_POLICY_LEGACY_COMPAT'] = False
    password = 'fixture-only-password-2026'
    rows = [Employee(username=name, display_name=name, role='admin',
                     password_hash=hash_password(password))
            for name in ('fixture-owner', 'fixture-a', 'fixture-b', 'fixture-c')]
    db.session.add_all([*rows, Terminal(code='ENTRY-TEST', name='隔离测试终端')])
    db.session.flush()
    ids = [row.id for row in rows]
    state = db.session.get(BusinessStateModel, 1)
    state.policy_version = 1
    db.session.add(AccessPolicyModel(owner_id=ids[0], mobile_employee_ids=ids[1:3],
        administrator_employee_ids=ids[1:], policy_version=1, is_active=True))
    db.session.commit()
    data = client.post('/api/auth/login', json={'username':'fixture-owner',
        'password':password, 'terminal_code':'ENTRY-TEST', 'client_channel':'desktop'}).get_json()['data']
    return {'owner_id':ids[0], 'administrator_ids':ids[1:], 'password':password,
        'headers':{'Authorization':f"Bearer {data['access_token']}",
                   'X-Business-Period':state.period_id}, 'terminal_code':'ENTRY-TEST'}
```

红测验证字段缺失和模板拒绝非法入口：

```python
def test_entry_model_and_template():
    from app.models import Employee
    from app.employee_access import validate_employee_channels
    assert {'allowed_channels', 'deleted_at'} <= set(Employee.__table__.columns.keys())
    assert validate_employee_channels('cashier', ['web','desktop']) == ['desktop','web']
    with pytest.raises(ApiError):
        validate_employee_channels('cashier', ['mobile'])
```

- [ ] **2. 红测命令。** 根目录设置 `PYTHON_DOTENV_DISABLED=1` 后运行 `server/.venv/Scripts/python.exe -m pytest server/tests/test_employee_entries.py -q`。预期缺少模块/字段失败，不能因生产数据库连接失败而算红测。
- [ ] **3. 字段和校验实现。** Employee 增加 JSON allowed_channels，非空默认 `[]`；deleted_at 时区时间 nullable。Alembic `revision='20261004_employee_entries'`，`down_revision='20261003_preserve_administrators'`，只加字段，已有普通账号不擅自授权：

```python
with op.batch_alter_table('employees') as batch:
    batch.add_column(sa.Column('allowed_channels', sa.JSON(), nullable=False, server_default='[]'))
    batch.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
```

校验入口必须是唯一的字符串列表、属于 desktop/web/mobile、匹配角色允许列表。未知角色/任意 permission_scope/未绑定 admin 不授最高权限。session_permissions 保留绑定账号路径，再对未绑定普通角色检查 allowed_channels；mobile 库管允许 inventory:read/write 而不是要求 mobile:order。服务员工权限增加 visit:read、visit:order、mobile:order，收银员增加 visit:order，库管去掉 settings:read；目录页面由 ui_pages 而非内部 catalog:read 授予。动作拒绝固定 `PERMISSION_DENIED`；真实入口禁用仍为 `CHANNEL_FORBIDDEN`。
- [ ] **4. 绿测与迁移测试。** 同命令通过；复制既有 test_administrator_policy_migration.py 的隔离迁移配置方式，在 tmp_path 库从前一 head 升级，确认默认 []、旧 UUID/密码/角色不变、单一 head。检查 mobile-only 管理员不能因为普通渠道模板登录桌面。
- [ ] **5. 提交。** 明确加入本任务七个源码文件、fixture、两个新测试/迁移文件；`git diff --cached --check` 后提交 `feat: add explicit employee entry grants and page capabilities`。不能暂存生产配置。

### A2：普通员工增删改与动作级错误

**Files:** 修改 server/app/api/employees.py、auth_service.py、serializers.py、client/src/api/http.ts、mobile/src/api.ts；新建 server/tests/test_employee_lifecycle.py；扩展 client/src/api/http.test.ts、mobile/src/api.test.ts。

**Interfaces:** POST/PATCH employees 支持 allowed_channels、is_active；GET `?deleted=only` 查看逻辑删除；DELETE `/employees/<uuid>` 返回标准 API envelope。员工 DTO 增加 allowed_channels、deleted_at、protected_account；不返回 password_hash。

- [ ] **1. 红测最小流程及会话保护。**

```python
def test_create_enable_does_not_revoke_owner(client, strict_owner_session):
    headers = strict_owner_session['headers']
    response = client.post('/api/employees', headers=headers, json={
        'username':'fixture-cashier', 'display_name':'测试收银', 'role':'cashier',
        'password':'fixture-cashier-2026', 'allowed_channels':['desktop','web'], 'is_active':True})
    assert response.status_code == 201
    assert response.get_json()['data']['is_active'] is True
    assert client.get('/api/business/state', headers=headers).status_code == 200
    assert db.session.get(BusinessStateModel, 1).policy_version == 1
```

同时添加：真实新员工登录成功；对无授权入口启用失败不注销 owner；DELETE 后原 UUID/audit 保留、登录和旧 JWT 均失败；删除自己/绑定管理员 403；重复 DELETE 不重复新增审计；deleted=only 可查；已删除用户名再创建 409；PATCH 无法恢复已删除；改角色仅目标 session_version 增加。

Axios 红测沿用当前 adapter 模式：对 `/employees/id` 构造 `AxiosError` 响应 `{success:false,error:{code:'PERMISSION_DENIED'}}` status403，断言 `getAccessToken()` 仍为 current；另测401 SESSION_REVOKED/403 CHANNEL_FORBIDDEN 确实清会话。

- [ ] **2. 运行红测。** `python -m pytest server/tests/test_employee_lifecycle.py -q`；client `npx.cmd vitest run src/api/http.test.ts`；mobile `npx.cmd vitest run src/api.test.ts`。记录每个预期失败断言。
- [ ] **3. 实现事务。** 创建用校验后的入口/实际启用状态；PATCH 对目标行 `with_for_update`，删除账号拒绝普通改动，绑定管理员禁用/降级/删除走受保护错误；只在目标安全字段改变时 session_version++。逻辑删除核心：

```python
employee.deleted_at = utcnow()
employee.is_active = False
employee.allowed_channels = []
employee.session_version += 1
write_audit('employee.delete', 'employee', employee.id,
    {'username':employee.username, 'role':employee.role, 'deleted_at':employee.deleted_at.isoformat()})
db.session.commit()
revalidate_sockets()
```

执行前验证 actor 不是目标且目标不 protected；已删重复调用直接返回，不复活。普通动作/目标授权错误不用 CHANNEL_FORBIDDEN；HTTP 拦截器继续对真实会话失败清理，不能笼统忽略所有403。新增中文审计标签“删除员工账号”。
- [ ] **4. 绿测回归。** 跑上述测试及 test_access_policy.py、test_auth_sessions.py、test_preserved_administrators.py。原有“有效手机会话访问禁止动作”测试期望调整为 PERMISSION_DENIED，保持403；缺失/伪造入口与身份绑定测试不得删除或改成允许。
- [ ] **5. 提交。** `fix: separate action denial from session revocation and add employee soft delete`，只提交本任务源文件和测试。

### A3：跨浴区和服务范围的服务端边界

**Files:** 新建 server/app/ordering_scope.py、server/tests/test_staff_ordering_scope.py；修改 server/app/api/visits.py、wristbands.py、catalog.py、mobile.py、access_policy.py。

**Interfaces:** `can_read_visit(employee: Employee, wristband: Wristband, visit: Visit) -> bool`；`can_sell_catalog(employee: Employee, catalog: CatalogItem) -> bool`；`require_order_target(employee: Employee, wristband: Wristband, visit: Visit) -> None`，不允许时抛 PERMISSION_DENIED。三函数均在本任务实现。

A 阶段浴区读取复用现有 wristband_area；C2 后改读 wristband.bath_area。范围：男 scrub=male/scrub+both，女 scrub=female/scrub+both，floor=male+female/rest+both，前台/最高管理员按其入口许可，库管不得点单。

- [ ] **1. 红测真实请求。** 使用 A2 创建 male_scrubber/female_scrubber/floor_attendant、赋渠道并真实登录；用 owner 开男 8001/女 9001，联动后员工 GET 男 visit 不能包含女 linked_visits；员工直接 POST 女 visit 或 frontdesk/rest 商品被403/404拒绝，库存/订单不变；直接 GET 全部 wristbands 只返回自己浴区 in_use，不能读空闲/历史账单；前台账号完整联动读取正常。

```python
@pytest.mark.parametrize('role,area,expected', [
    ('male_scrubber','male',True), ('male_scrubber','female',False),
    ('female_scrubber','male',False), ('female_scrubber','female',True),
    ('floor_attendant','male',True), ('floor_attendant','female',True),
    ('inventory','male',False),
])
def test_active_order_target_scope(role, area, expected):
    employee = Employee(role=role, allowed_channels=['desktop','mobile'])
    band = Wristband(number='8001' if area == 'male' else '9001', status='in_use')
    visit = Visit(status='open')
    assert can_read_visit(employee, band, visit) is expected
```

上述纯scope用例之外，必须用真实HTTP和JWT验证返回字段及拒绝后库存不变；不能只测mock函数。
- [ ] **2. 运行。** `python -m pytest server/tests/test_staff_ordering_scope.py server/tests/test_mobile_ordering.py -q`，预期原固定名单或范围泄漏的明确断言失败。
- [ ] **3. 接入统一范围。** visits GET/单条和批量加单、mobile bootstrap/加单都用上述函数；先锁 visit，再校验范围，再锁各 catalog（按 UUID 排序），最后扣库存。读取 linked_visits 时过滤每个成员再计算可见合计。加单改 require_permission('visit:order')；开牌/换牌/挂失/联动/清空仍 visit:write 或既有更强权限。catalog GET 允许营业读取但过滤可售范围，inventory 走自己的库存 API，不赋 settings 页面。拒绝未知范围，不能根据客户端 bath_area/mobile_scope 放行。

```python
visible = [row for row in linked_visits
           if can_read_visit(employee, db.session.get(Wristband, row.wristband_id), row)]
if visit.id not in {row.id for row in visible}:
    raise ApiError('无权访问该手牌', 403, 'PERMISSION_DENIED')
```

mobile `_policy` 由真实角色/绑定管理身份决定，删除“有 mobile:order 即全部权限”的捷径；EVENT_PERMISSIONS 中目录变更增加库存读取受众，事件仅带资源标识，实际数据仍由 API 过滤。
- [ ] **4. 绿测。** 服务角色矩阵、直接 API 绕过、跨浴区联动、批量越权回滚、越权不扣库存、Socket 对目标停用断开全部通过；运行原 test_main_flow.py/test_mobile_management.py 保留管理员完整功能。
- [ ] **5. 提交。** `fix: enforce role scoped wristband and catalog access on every ordering API`。

### A4：桌面员工界面和路由能力

**Files:** 新建 client/src/navigation/access.ts、access.test.ts、views/EmployeesView.test.ts；修改 EmployeesView.vue、DashboardView.vue、VisitView.vue、navigation/menu.ts、router/index.ts、business/state.ts、types.ts、layouts/ShellLayout.vue。

**Interfaces:** `pageAllowed(uiPages:string[], path:string, capabilities:Record<string,boolean>):boolean`；`landingPath(uiPages:string[]):string`。业务 state 新增 ui_pages/capabilities，auth 接收服务器能力；role 本身不授最高页面。结账子路径必须另外检查checkout_write，不能因员工也有wristbands页面放行。

- [ ] **1. 红测菜单和表单。**

```ts
it('cashier has exactly three business pages', () => {
  const pages = ['wristbands','members','print-jobs']
  const capabilities = {checkout_write:true, member_write:true, receipt_reprint:true}
  expect(pageAllowed(pages, '/print-jobs', capabilities)).toBe(true)
  expect(pageAllowed(pages, '/reports', capabilities)).toBe(false)
  expect(pageAllowed(pages, '/checkout', capabilities)).toBe(true)
  expect(pageAllowed(['wristbands'], '/checkout', {checkout_write:false})).toBe(false)
  expect(landingPath(['inventory'])).toBe('/inventory')
})
```

EmployeesView mount 使用真实表单 UI 和 mock HTTP：选择岗位、入口、启用后请求体正确；删除确认调用 DELETE，取消不调用；protected_account 没有删除入口；删除筛选携带参数；403 提示不卸载管理页面。Dashboard/Visit 的员工角色没有开牌、清空、结账/撤销按钮。缺 ui_pages 的新登录明确报后端版本不兼容，不能推测成全权限。
- [ ] **2. 运行。** client `npx.cmd vitest run src/navigation/access.test.ts src/views/EmployeesView.test.ts`，记录红测。
- [ ] **3. 实现路由表和表单。** pageAllowed 将 `/visits/*` 映射 wristbands、`/members/*` 映射 members、`/checkout` 仅前台 capability、其它九个主页面精确映射；未知路径拒绝。表单入口 checkbox 随岗位联动，只发 allowed_channels；新增也显示启用开关；单次保存/删除 busy 防重复，反馈具体错误。导航与 route.beforeEach 使用同一 access 函数。员工手牌视图只呈现读/点单，不靠 CSS 隐藏动作。

```ts
export function pageAllowed(pages: string[], path: string, caps: Record<string,boolean>): boolean {
  if (path === '/checkout') return pages.includes('wristbands') && caps.checkout_write === true
  if (path === '/' || /^\/visits\/[^/]+$/.test(path)) return pages.includes('wristbands')
  if (/^\/members\/[^/]+\/(recharge|pass-purchase)$/.test(path))
    return pages.includes('members') && caps.member_write === true
  const exact = new Map([
    ['/members','members'],['/print-jobs','print-jobs'],['/catalog','catalog'],
    ['/inventory','inventory'],['/reports','reports'],['/audit','audit'],
    ['/employees','employees'],['/settings','settings'],
  ])
  const page = exact.get(path)
  return page !== undefined && pages.includes(page)
}
```

登录/连接设置辅助入口在身份流程单独处理，不将未知营业route作为允许入口。
- [ ] **4. 绿测。** 上述测试加 menu/shortcuts/auth/business 原测试及 npm.cmd run type-check。收银会员子页面和补打流程可用；库管错误路由回库存而非无权限手牌造成循环。
- [ ] **5. 提交。** `feat: add employee entry controls delete and server driven desktop navigation`。

### A5：手机库存角色和会话实时撤销

**Files:** 修改 server/app/api/auth.py、mobile.py、mobile/src/types.ts、mobile-role.ts、mobile-management.ts、router/access.ts、router/index.ts、components/navigation/MobileBottomNav.vue、stores/session.ts；扩展 server/tests/test_mobile_management.py、mobile/src/router/access.test.ts、mobile-role.test.ts、mobile-management.test.ts、stores/session.test.ts、composables/useRealtime.test.ts。

**Interfaces:** mobile capabilities 新增 `orders_view`；stock 角色 `{orders_view:false, reports_view:false, inventory_manage:true}`；服务员工 orders true 其余 false；绑定管理员保留原管理能力。`mobileLanding(capabilities:{orders_view:boolean,reports_view:boolean,inventory_manage:boolean}):'/inventory'|'/orders'|'/login'`，无任何业务能力转login，不循环跳转。

- [ ] **1. 红测。** 库管 mobile 真实登录200，bootstrap 无手牌/catalog泄漏、库存读写正常、直接点单/报表拒绝；服务员工只有点单 tab；mobile 员工移除入口后原 JWT 和 Socket 失效，owner socket 不失效。手机路由输入 /orders 拒绝库管并落库存；个人/退出辅助仍可用。

新增明确验收：对三位既有绑定管理员的UUID分别真实mobile登录、bootstrap全部bath/catalog、reports/inventory访问；同名未绑定admin必须仍403。R3提供只读channel诊断（实际active policy、UUID、is_active/role、terminal、channel与错误码），如果云端缺UUID绑定则停止并输出需核对的IDs，提供保留owner/所有旧管理员的显式维护修复命令；不自动依名字赋权或将手机scope改为'*'。手机登录错误区分通道拒绝、策略未配置、终端停用、会话撤销和网络超时，给下一步操作，不把所有问题统称Network Error。

```ts
it('inventory only accounts land on inventory, never orders', () => {
  expect(mobileLanding({orders_view:false,reports_view:false,inventory_manage:true}))
    .toBe('/inventory')
  expect(mobileLanding({orders_view:false,reports_view:false,inventory_manage:false}))
    .toBe('/login')
})
```
- [ ] **2. 运行。** `python -m pytest server/tests/test_mobile_management.py server/tests/test_staff_ordering_scope.py -q`；mobile `npx.cmd vitest run src/router/access.test.ts src/mobile-role.test.ts src/mobile-management.test.ts src/stores/session.test.ts src/composables/useRealtime.test.ts`。
- [ ] **3. 实现。** auth mobile 校验改为 session_ui 的允许业务页而非必须 mobile:order；mobile bootstrap permission-any 接受 mobile:order 或 inventory:read，但分别构造最小数据。管理库存基于 inventory 权限和允许入口，不等于手机 full_admin。mobile types 加 inventory，底栏 orders 不再永远显示；登录、无权跳转均用 mobileLanding。真实撤销沿用 revalidate_sockets + 原 generation 清理，普通动作拒绝不清理。

```ts
export function mobileLanding(caps: {orders_view:boolean;reports_view:boolean;inventory_manage:boolean})
    : '/inventory' | '/orders' | '/login' {
  if (caps.orders_view) return '/orders'
  if (caps.inventory_manage) return '/inventory'
  return '/login'
}
```

生产backend `_capabilities` 的orders_view必须从当前会话visit:order/mobile:order和允许入口推出；inventory_manage从inventory:write推出，而不是旧_has_management_access的mobile:order捷径。bootstrap库管返回空wristbands/catalog和库存业务能力，库存数据独立授权API读取。
- [ ] **4. 绿测及完整权限回归。** 执行 A 全部后端和双前端测试；核对设计验收1–5、14通过。legacy 模式仅测试可用，生产始终 fail-closed，不新增环境变量关闭权限检查。
- [ ] **5. 提交。** `feat: support inventory only mobile accounts and targeted session invalidation`，记录 A 验收结果后交 B。
