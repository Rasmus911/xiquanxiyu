# Desktop 0.5.0 Accounts and Isolated Daily Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 发布可从旧版登录页联网覆盖升级的桌面 0.5.0，实现真正删除员工账号、本人改密、服务岗位本机 58mm 下单打印及两类独立的当日补打。

**Architecture:** 把认证账号与历史责任身份分离，保持历史 UUID 及审计哈希不变。保留结账 PrintJob，新增独立的服务下单任务及尝试记录；后端控制两类权限、自然日有效期和幂等，Electron 负责本机打印。交付在复用原签名信任与可恢复部署检查点的基础上构建，不自动操作生产库。

**Tech Stack:** Vue 3、TypeScript、Element Plus、Pinia、Electron、Python/Flask、SQLAlchemy/Alembic、PostgreSQL 17、pytest、Vitest、Node test runner、Windows PowerShell 5.1、Docker/SSH。

**Spec:** `F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-11-desktop-050-accounts-receipts-design.md`

## Global Constraints

- 桌面版本 `0.5.0`；从 `0.4.9`、`0.4.8` 及仍受支持的更低版本登录页检查更新，不先登录、不先卸载、不替换原公钥。
- 登录标题“平泉市溪泉洗浴”；删除“手牌、收银、会员、库存与经营报表”。
- 所有桌面角色有“账号密码修改”，登录账号只读，旧密码核对后修改本人密码。
- `male_scrubber`、`female_scrubber`、`floor_attendant` 加单才自动打印，打印机为下单电脑连接的 58mm 打印机。
- 下单小票与结账小票的列表、记录、状态和次数独立；最高权限可以访问两类。
- 普通服务岗位只能访问下单小票；其他原补打岗位只能访问结账小票；保留各自现有手牌范围。
- 自然日 `Asia/Shanghai`，00:00 含、次日 00:00 不含；只清理过期小票业务数据，保留金融和不可修改的审计数据。
- 删除账号后旧凭证失效，同手机号新注册产生新 UUID；不删除历史责任身份，不把历史关联到新账号。
- 现有不可变的 `registration_receipts`、`registration_token_views`、`revoked_sessions` 是历史安全证据，不删除、不撤掉触发器；原注册回执的认证重试失效。
- 不新增 Android 本地打印、不改手机 1.2.9 版本和原证书；回归原手机功能，不构建 Win7。
- 交付目录 `F:/溪泉洗浴系统/最新版安装包-账号与小票-0.5.0`；保留原有四个发布目标 `win10-x86`、`win10-x64`、`win11-x86`、`win11-x64`，x86 指应用位数，不声称 Windows 11 存在 32 位操作系统。
- 对外更新日志仅为四条：优化主登录页面；新增账号密码修改功能；新增搓澡师下单打印小票的功能；新增每天小票补打的功能。
- GitHub 归档位置 `https://github.com/Rasmus911/xiquanxiyu`；通过指定 GitHub Desktop 操作源码上传，安装包放 Releases，核对远端后再精确清理。
- 不上传 `.env`、生产数据库、会员信息、真实凭证、PEM 私钥或 Android JKS；不改用户现有三个未跟踪文件。

## 工作顺序、文件边界与命令约定

顺序：历史身份/删除 → 本人改密 → 登录与账号 UI → 下单打印 API → 本机打印 → 当日补打/清理 → PostgreSQL/部署 → 正式更新包 → 归档清理。

现有大文件只保留调用点，新行为放入职责单一的模块。不得复制 0.4.9 部署脚本后只改版本号：其旧 schema、手机版本、快照对比和私钥默认路径均须实质更新。

Python 测试从 `F:/溪泉洗浴系统/server` 运行，命令前缀为 `& '.\.venv\Scripts\python.exe' -m pytest`；前端从 `F:/溪泉洗浴系统/client` 运行，命令前缀为 `npm.cmd exec -- vitest run`。脚本 pytest 同样从 server 运行，目标使用 `..\scripts\tests\` 下的具体文件。测试固定使用 TestConfig/独立 SQLite 或明确隔离 PostgreSQL URL，不能读取生产 `.env`。

新的结构迁移链为 `20261008_registration_token` → `20261011_employee_identity` → `20261011_service_receipts`。正式云端目标 head 为 `20261011_service_receipts`。

## Task 1: 责任身份、历史外键迁移与真正删除员工

**Files:**
- Create: `server/app/employee_identity.py`（无认证凭证的历史身份与创建/查找）；`server/migrations/versions/20261011_employee_identity.py`。
- Modify: `server/app/models.py`、`registration_models.py`、`api/employees.py`、`auth_service.py`、`registration_service.py`、`api/audit.py`、`serializers.py`、`database_guards.py`。
- Test: `server/tests/test_employee_lifecycle.py`、`test_employee_identity050.py`、`test_employee_identity050_migration.py`、`test_registration049.py`、`conftest.py`。

**Interfaces:**
- Produces: `EmployeeIdentity(id, username, display_name, role, created_at)`；`ensure_employee_identity(connection, employee) -> None`；`historical_employee(employee_id, session) -> Employee | EmployeeIdentity | None`。
- Auth remains `employee_for_claims(claims) -> Employee`：永远不从 EmployeeIdentity 获得登录主体。
- DELETE `/api/employees/<id>` 返回 `{'id': id, 'deleted': True}`；相同已删除 ID 重试返回 404 `NOT_FOUND`，不复活账号。
- 注册回执找不到真实账号时返回 409 `REGISTERED_ACCOUNT_REMOVED`。

- [x] **Step 1: 写出真实删除回归测试及复用的普通岗位测试工厂。** 在 conftest 增加 `desktop050_employee_session(client, strict_owner_session)` 返回下面的工厂；每个测试使用独立数据库，手机号不触发短信。

```python
import pytest

@pytest.fixture
def desktop050_employee_session(client, strict_owner_session):
    def create_session(role='cashier', username='13800000001'):
        password = 'fixture-employee-password-2026'
        created = client.post('/api/employees', headers=strict_owner_session['headers'], json={
            'username': username, 'display_name': '隔离员工', 'role': role,
            'password': password, 'allowed_channels': ['desktop'], 'is_active': True,
        })
        assert created.status_code == 201
        logged = client.post('/api/auth/login', json={
            'username': username, 'password': password, 'client_channel': 'desktop',
            'terminal_code': strict_owner_session['terminal_code'],
        })
        assert logged.status_code == 200
        data = logged.get_json()['data']
        return {'id': created.get_json()['data']['id'], 'username': username, 'password': password,
            'login': data, 'headers': {'Authorization': 'Bearer ' + data['access_token'],
                                     'X-Business-Period': data['business_state']['period_id']}}
    return create_session

def test_delete_releases_username_preserving_evidence(client, strict_owner_session,
                                                     desktop050_employee_session):
    from app.models import Employee, AuditLog
    from app.extensions import db
    from app.audit_service import verify_audit_chain
    first = desktop050_employee_session()
    before = [(row.id, row.current_hash) for row in AuditLog.query.order_by(AuditLog.chain_index)]
    response = client.delete('/api/employees/' + first['id'], headers=strict_owner_session['headers'])
    assert response.status_code == 200
    assert db.session.get(Employee, first['id']) is None
    second = desktop050_employee_session(username=first['username'])
    assert second['id'] != first['id']
    after = [(row.id, row.current_hash) for row in AuditLog.query.order_by(AuditLog.chain_index)]
    assert after[:len(before)] == before
    assert verify_audit_chain() == (True, None)
    assert client.get('/api/business/state', headers=first['headers']).status_code == 401
```

- [x] **Step 2: 运行红灯测试。** `& '.\.venv\Scripts\python.exe' -m pytest tests/test_employee_identity050.py -q`，旧实现必须在员工行仍存在处失败。保持“禁止删除自己/最高管理员”和“仅目标会话撤销”原测试；将旧 `test_soft_delete_retains_identity_audit_and_invalidates_old_token` 的占用手机号预期替换为新版明确规则，不整体删除测试文件。
- [x] **Step 3: 实现身份及认证分离。** 身份插入在 Employee `after_insert` 同一连接完成，确保管理员创建、首次初始化、动态注册及隔离 fixture 都有身份；不保存 password_hash。迁移使用原 UUID 回填，再定向替换下面的历史外键，所有原行值保持不变。

```python
HISTORICAL_EMPLOYEE_REFERENCES = {
    'audit_logs': ('employee_id',), 'revoked_sessions': ('employee_id',),
    'visits': ('opened_by_id',),
    'order_items': ('service_employee_id', 'created_by_id', 'voided_by_id'),
    'shifts': ('employee_id',), 'settlements': ('created_by_id',),
    'stored_value_ledgers': ('operator_id',), 'pass_ledgers': ('operator_id',),
    'inventory_movements': ('operator_id',), 'stock_movements': ('operator_id',),
    'stock_costs': ('operator_id',), 'registration_receipts': ('employee_id',),
    'registration_token_views': ('employee_id',),
}
# 权限策略/重置所有者仍 FK 到 employees，不能删除受保护主体。
# 创建责任身份后：db.session.delete(employee)，而不是更改用户名或 deleted_at。
# 旧注册回执返回前：真实 Employee 缺失/已删除 -> REGISTERED_ACCOUNT_REMOVED。
```

使用 inspector 的约束名称作 PostgreSQL DROP/ADD FK，禁止改审计内容或关闭不可变触发器。SQLite 迁移演练的外键暂停必须发生在 DDL 事务前，完成后恢复并 `PRAGMA foreign_key_check`；不用 writable_schema。清理既有软删除员工前保护策略绑定。责任身份只允许 INSERT/SELECT，老注册回执、撤销记录继续不可变。写请求先取得写屏障和认证员工锁，再取得财务/目标锁；删除完成后的旧会话不能继续提交。
- [x] **Step 4: 演练旧 head 数据迁移及历史展示。** 比较所有历史业务行、审计哈希、历史责任人；检查新表不含凭证，旧登录被拒绝、新 UUID 不承接旧交易；覆盖已软删除普通账号、v1 审计查找回退、注册旧回执重试、竞争删除/下单。`& '.\.venv\Scripts\python.exe' -m pytest tests/test_employee_identity050.py tests/test_employee_identity050_migration.py tests/test_employee_lifecycle.py tests/test_registration049.py -q`。
- [x] **Step 5: 仅提交本任务列出的文件。** `git commit -m "feat(accounts): separate historical identities and physically delete logins"`，不得 `git add .`。

Task 1 execution evidence (2026-10-11): physical deletion RED then GREEN; 75 related checks passed before the SQLite writer reservation, and the final migration/deletion/independent-connection lock selection passed 19 tests. Registration regression also passed with the reservation. Historical table creation is frozen through `schema_history.py`, including the old registration migration; SQLite table recreation uses scoped `legacy_alter_table`, never `writable_schema` or disabling audit immutability. Independent SQLite writers cannot delete a principal while a mutation holds its reservation. PostgreSQL 17 role/concurrency rehearsal remains Task 7; no cloud mutation has been performed.

## Task 2: 本人密码修改与会话撤销

**Files:**
- Create: `server/app/account_service.py`；`server/tests/test_account_password050.py`。
- Modify: `server/app/api/auth.py`、`employee_access.py`、`serializers.py`。

**Interfaces:**
- Consumes: Task 1 真实 Employee 认证与锁；现有 `hash_password`、`verify_sensitive_password`、`revalidate_sockets`。
- Produces: POST `/api/auth/change-password`，仅接受 `old_password`、`new_password`、`confirm_password`，成功 data `{'relogin_required': True}`。
- 会话 UI：非手机合法账号有 `account-password` 页面及 `account_password_change=True`；服务岗位只增加此自助能力，不赋予员工管理权限。

- [x] **Step 1: 先写旧密码核对、本人限制及双令牌撤销测试。**

```python
def test_self_change_invalidates_both_old_tokens(client, desktop050_employee_session):
    session = desktop050_employee_session('male_scrubber')
    response = client.post('/api/auth/change-password', headers=session['headers'], json={
        'old_password': session['password'], 'new_password': 'new-isolated-password-2026',
        'confirm_password': 'new-isolated-password-2026',
    })
    assert response.status_code == 200
    assert response.get_json()['data'] == {'relogin_required': True}
    assert client.get('/api/auth/me', headers=session['headers']).status_code == 401
    assert client.post('/api/auth/refresh', headers={
        'Authorization': 'Bearer ' + session['login']['refresh_token']}).status_code == 401
```

- [x] **Step 2: 运行** `& '.\.venv\Scripts\python.exe' -m pytest tests/test_account_password050.py -q`，先确认旧实现返回 404。
- [x] **Step 3: 实现最小自助改密。** 验证 JSON 为对象且键集合准确、三项均为字符串；旧密码错误走原五次锁定机制；拒绝不一致、相同密码及不符合长度的新密码。真实主体由 current_employee 定位，不能接受 employee_id。更新 hash 和 session_version、写 `account.password_change` 无密码审计，提交后 revalidate_sockets。会话 UI 只增加自助页面，不改手机范围或注册令牌权限。

```python
verify_sensitive_password(employee, body['old_password'])
if body['new_password'] != body['confirm_password']:
    raise ApiError('两次新密码不一致', 400, 'PASSWORD_CONFIRM_MISMATCH')
if body['new_password'] == body['old_password']:
    raise ApiError('新密码不能与旧密码相同', 400, 'PASSWORD_UNCHANGED')
employee.password_hash = hash_password(body['new_password'])
employee.session_version += 1
write_audit('account.password_change', 'employee', employee.id, {'sessions_revoked': True})
db.session.commit()
revalidate_sockets()
return success({'relogin_required': True}, '密码修改成功，请重新登录')
```

- [x] **Step 4: 运行改密与既有权限回归。** 覆盖全部七个角色、未知字段、错误类型、空字符串、锁定、保护管理员 UUID 不变、旧 access/refresh/socket 拒绝及新密码登录；`& '.\.venv\Scripts\python.exe' -m pytest tests/test_account_password050.py tests/test_auth_sessions.py tests/test_employee_entries.py -q`。
- [x] **Step 5: 提交** `feat(accounts): add self password change and invalidate old sessions`。

Task 2 evidence: the new endpoint first failed with 404; final password/session/channel regression passed 48 tests, including immediate socket disconnection for all seven desktop roles. No passwords are included in password-change audit details; no employee identifier is accepted in the request.

## Task 3: 登录布局、公共改密页面与员工列表

**Files:**
- Create: `client/src/views/AccountPasswordView.vue`、`AccountPasswordView.test.ts`、`LoginView.test.ts`。
- Modify: `client/src/views/LoginView.vue`、`EmployeesView.vue`、`client/src/navigation/menu.ts`、`access.ts`、`client/src/router/index.ts`、`components/app/AppSidebar.vue`、相关 navigation/view tests。

**Interfaces:**
- Consumes: Task 2 `/auth/change-password`；`clearBusinessSession()`、`useBusinessGuard()`；服务端 `ui_pages`。
- Produces: 路由 `/account-password` → 页面键 `account-password`；三个输入框测试 ID 为 `account-old-password`、`account-new-password`、`account-confirm-password`，提交 `account-password-submit`。

- [x] **Step 1: 写登录品牌与菜单/改密 UI 测试。**

```typescript
import { expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessage } from 'element-plus'
import AccountPasswordView from './AccountPasswordView.vue'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { setAccessToken } from '../auth/session'
import { acceptBusinessState, clearBusinessSession } from '../business/state'
import { pageAllowed } from '../navigation/access'

it('self-password is reachable without granting employee administration', () => {
  expect(pageAllowed(['wristbands', 'account-password'], '/account-password',
    { account_password_change: true })).toBe(true)
  expect(pageAllowed(['wristbands'], '/employees', {})).toBe(false)
})
it('mismatched passwords never submit to the server', async () => {
  clearBusinessSession()
  const pinia = createPinia()
  useAuthStore(pinia).employee = { id:'fixture', username:'13800000001',
    display_name:'隔离员工', role:'male_scrubber', is_active:true }
  setAccessToken('fixture-access')
  acceptBusinessState({ period_id:'fixture', policy_version:1, business_revision:0,
    maintenance:false, owner_reset_allowed:false,
    ui_pages:['wristbands','account-password'], capabilities:{account_password_change:true} }, ['visit:order'])
  const originalAdapter = http.defaults.adapter
  const adapter = vi.fn(async (config: any) => ({config, headers:{}, status:200,
    statusText:'OK', data:{success:true, data:{relogin_required:true}}}))
  http.defaults.adapter = adapter
  const router = createRouter({history:createMemoryHistory(), routes:[
    {path:'/account-password', component:AccountPasswordView}, {path:'/login', component:{template:'<div>login</div>'}}]})
  await router.push('/account-password'); await router.isReady()
  const wrapper = mount(AccountPasswordView, {global:{plugins:[pinia, router, ElementPlus]}})
  try {
    await wrapper.find('[data-testid="account-old-password"]').setValue('old-fixture-password')
    await wrapper.find('[data-testid="account-new-password"]').setValue('new-fixture-password')
    await wrapper.find('[data-testid="account-confirm-password"]').setValue('different-password')
    await wrapper.find('[data-testid="account-password-submit"]').trigger('click')
    await flushPromises()
    expect(adapter).not.toHaveBeenCalled()
    expect(document.body.textContent + wrapper.text()).toContain('两次新密码不一致')
  } finally {
    wrapper.unmount(); http.defaults.adapter = originalAdapter
    ElMessage.closeAll(); clearBusinessSession()
  }
})
```

- [x] **Step 2: 运行** `npm.cmd exec -- vitest run src/navigation/access.test.ts src/views/AccountPasswordView.test.ts src/views/LoginView.test.ts`，确认缺少页面/路由和旧标题造成红灯。
- [x] **Step 3: 实现 UI。** 登录采用主次两排入口，保留 Enter/Tab 和桌面注册/更新条件。改密页面显示只读用户名和姓名，旧/新密码使用正确 autocomplete、提交时禁重复/禁关闭；成功清空三个密码，`clearBusinessSession()` 后 router.replace('/login')，不调用已经撤销令牌的远端 logout。失败保留可纠正的输入，卸载/账号变化清空密码，迟到响应不清掉新会话。员工页移除已删除筛选和软删除状态文案，删除后刷新真实账号列表，不提供恢复入口。

```typescript
const generation = businessGeneration.capture()
await http.post('/auth/change-password', {
  old_password: oldPassword.value, new_password: newPassword.value,
  confirm_password: confirmPassword.value,
})
assertCurrent(generation)
oldPassword.value = ''; newPassword.value = ''; confirmPassword.value = ''
clearBusinessSession()
await router.replace('/login')
```

- [x] **Step 4: 运行 UI、菜单及员工页面测试与 type-check。** 验证全部角色菜单中包含改密，服务岗位不能到员工页面，旧“已删除账号”不再显示；登陆窗口宽/窄布局手动查看。`npm.cmd run type-check`，不能把只检查模板字符串当作完整页面验收。
- [x] **Step 5: 提交** `feat(ui): refresh login layout and add self password page`。

Task 3 evidence: RED on missing view/route, old branding and deleted-account filter; GREEN 24 Vitest checks plus vue-tsc. The local browser rendered both 1280×900 and 375×812 login layouts, screenshots visually inspected in private/desktop050-visual. Browser API requests were blocked, so no live server was used. Visual checks wait for Element Plus width transitions to settle before measuring overflow.

## Task 4: 独立下单任务、打印尝试与权限 API

**Files:**
- Create: `server/app/receipt_models.py`、`receipt_service.py`、`receipt_retention.py`（本任务先实现纯日期函数）、`api/service_print.py`、`server/migrations/versions/20261011_service_receipts.py`。
- Modify: `server/app/models.py`、`api/__init__.py`、`api/visits.py`、`api/errors.py`、`auth_service.py`、`employee_access.py`、`api/checkout.py`。
- Test: `server/tests/test_order_receipts050.py`、`test_receipt_permissions050.py`、`test_receipt_attempts050.py`。

**Interfaces:**
- Models: `ServicePrintJob` 独立于 PrintJob，包含 period_id、visit_id、terminal_id、employee_id（历史身份）、唯一 submission_key、snapshot、status、attempts、last_error、printed_at；`ServicePrintAttempt`、`SettlementPrintAttempt` 各自 FK 到所属任务，request_key 唯一，不混用。
- `create_service_print_job(session, employee, visit, items, terminal_id, submission_key) -> ServicePrintJob | None`，仅三个服务角色创建。
- 服务快照字段为 `receipt_kind:'order'`、`job_id`、`wristband_number`、`bath_area`、`employee_name`、`employee_username`、`created_at`、`expires_at`、`items:[{name,quantity,total_amount}]`；序列化不依赖员工账号仍存在，任务首次创建日/浴区/责任人不可被客户端覆盖。
- 加单响应保留原 data 数组/对象；可选顶层 `meta.service_print_job` 为 `{id, kind:'order', created_at, expires_at}`。`success(data=None, message='操作成功', status=200, meta=None)` 未传 meta 时完全保持旧响应。
- Produces: `business_day_bounds(now: datetime) -> tuple[datetime,datetime]`、`next_midnight(created_at: datetime) -> datetime`、`require_current_receipt(job, now: datetime) -> None`；UTC 存储，边界固定 UTC+8，过期报 410 `RECEIPT_EXPIRED`。Task 6 复用这些函数，不重新定义日期规则。
- GET `/api/service-print-jobs?page=1&page_size=10` 返回 data `{items,total,page,page_size,server_time,expires_at}`；GET `/<id>/receipt` 返回服务器快照。
- POST `/<id>/attempts` 接受 `{request_key, mode:'automatic'|'manual'}`，返回 `{id,print_allowed,receipt}`；POST `/<id>/attempts/<attempt_id>/result` 接受 `{success:boolean,error?:string}`。
- 结账对应 POST `/api/checkout/<settlement_id>/print-attempts`、POST `/print-attempts/<attempt_id>/result`；原 `/print-result` 仍接受旧格式，新版使用明确尝试编号保证幂等。
- 结账列表带 `paged=true` 和三个显式 status 时返回分页对象；不带 paged 的旧调用仍返回数组。
- 新权限 `print:order` 只进入三个服务角色模板；有效 `*` 会话获得两类访问。手机不增加此打印权限。

- [x] **Step 1: 创建真实加单 fixture 与独立任务红灯。** 使用 Task 1 工厂，在严格 owner 下给 8001 或 9001 开牌、选 `mobile_scope='scrub'`/`rest` 的真实可售项目，下单版本从 Visit 读取；请求使用 manual 空耗材并非伪造价格。

```python
def test_batch_order_has_one_separate_job_on_retry(client, strict_owner_session,
                                                  desktop050_employee_session):
    from app.extensions import db
    from app.models import Wristband, Visit, CatalogItem, OrderItem, PrintJob
    from app.receipt_models import ServicePrintJob
    worker = desktop050_employee_session('male_scrubber')
    band = Wristband.query.filter_by(number='8001').one()
    opened = client.post('/api/wristbands/' + band.id + '/open',
        headers=strict_owner_session['headers'], json={})
    visit = db.session.get(Visit, opened.get_json()['data']['id'])
    catalog = CatalogItem.query.filter_by(is_active=True, mobile_scope='scrub').first()
    payload = {'version': visit.version, 'items': [{'catalog_item_id': catalog.id,
        'quantity': 1, 'inventory_mode': 'manual', 'inventory_consumption': []}]}
    headers = {**worker['headers'], 'Idempotency-Key': 'one-isolated-submission'}
    path = '/api/visits/' + visit.id + '/items/batch'
    before = OrderItem.query.count()
    first = client.post(path, headers=headers, json=payload)
    assert first.status_code == 201
    second = client.post(path, headers=headers, json=payload)
    assert first.get_json()['meta']['service_print_job']['id'] == second.get_json()['meta']['service_print_job']['id']
    assert ServicePrintJob.query.count() == 1
    assert PrintJob.query.count() == 0
    assert OrderItem.query.count() == before + 1
```

- [x] **Step 2: 运行** `& '.\.venv\Scripts\python.exe' -m pytest tests/test_order_receipts050.py tests/test_receipt_permissions050.py tests/test_receipt_attempts050.py -q`，确认缺少任务模块/接口，随后实现。
- [x] **Step 3: 在同一加单事务中创建任务并保存幂等 meta 引用。** 不把整份小票 JSON 放入不可变金融 IdempotencyRecord；只保存任务 ID，午夜不会重写金融幂等。单项和批量加单均覆盖；手机旧接口结构不变，不承诺手机打印。snapshot 从落账 OrderItem、真实 Employee 和 Wristband 创建，只包含本批次。

```python
job = create_service_print_job(db.session, employee, visit, items,
    get_jwt()['terminal_id'], idempotency_record_key(endpoint, employee.id, raw_key))
meta = {'service_print_job': {'id': job.id, 'kind': 'order',
    'created_at': job.created_at.isoformat(), 'expires_at': next_midnight(job.created_at).isoformat()}} if job else None
# 在同一次 commit 前保存 {'data': payload, 'meta': meta}；重放只取原 meta。
# 先 db.session.commit()，后发送成功响应；打印不在数据库事务内执行。
```

尝试开始锁定任务，自动尝试只允许一次，第二次/丢失响应只返回 print_allowed=False；人工补打可新建尝试。相同 request_key 返回原尝试且不重新授权出纸；每个首次结果增加一次 attempts，相同结果重放不计数，矛盾结果返回 409。只允许任务授权范围内的当前身份操作，错误类型/超长 error 截断或拒绝，禁止跨类型 ID。最高权限仍走 effective_permissions，不以手机号认定。
- [x] **Step 4: 运行全角色与事务回归。** 覆盖服务三岗位、cashier/inventory 不建任务、最高权限两类型、非法金额/身份字段、不匹配浴区、事务失败无任务、重放一个任务、结果重放/冲突、两个任务的次数独立。`& '.\.venv\Scripts\python.exe' -m pytest tests/test_order_receipts050.py tests/test_receipt_permissions050.py tests/test_receipt_attempts050.py tests/test_staff_ordering_scope.py tests/test_order_target_version.py -q`。
- [x] **Step 5: 提交** `feat(receipts): add independent staff order jobs and guarded print attempts`。

执行证据：先缺少 receipt_models 的红灯，随后 78 项相关后端测试通过（29.15秒）。含真实 SQLite 迁移、手机加单和混合收款回归；未声称已在 PostgreSQL 云端部署或实体打印机验收。

## Task 5: 58mm 下单模板与加单后本机打印

**Files:**
- Create: `client/electron/service-receipt.cjs`、`service-receipt.node-test.cjs`；`client/src/domain/receipts/printing.ts`、`printing.test.ts`。
- Modify: `client/electron/receipt.cjs`、`client/src/composables/useVisitOrdering.ts`、其测试、`views/VisitView.vue`、`views/CheckoutView.vue`、`client/src/types.ts`。

**Interfaces:**
- `serviceReceiptHtml(receipt) -> string`；`receiptHtml` 按服务器提供的 `receipt_kind='order'` 调用它，否则保留原结账模板。
- `ServicePrintReference = {id:string;kind:'order';created_at:string;expires_at:string}` 定义在 client/src/types.ts；`SubmissionSnapshot` 沿用 client/src/domain/orders/visit-drafts.ts 的现有类型，不新增 acknowledge 方法。
- `OrderSubmissionResult = {target: SubmissionSnapshot; servicePrintJob: ServicePrintReference | null}`；submitSnapshot/retryPending 返回它，所有 VisitView 调用点改用 result.target。
- `printServiceJob(jobId, mode, printerName, generation) -> Promise<{state:'success'|'failed'|'uncertain'|'skipped';message:string}>`，失败不抛出业务下单失败。

- [x] **Step 1: 写模板和异步打印红灯。**

```javascript
const { test } = require('node:test')
const assert = require('node:assert/strict')
const { serviceReceiptHtml } = require('./service-receipt.cjs')
test('service slip highlights band and never renders employee content as markup', () => {
  const html = serviceReceiptHtml({ wristband_number: '001', employee_name: '<script>bad()</script>',
    employee_username: '13800000001', items: [{ name: '搓澡', quantity: '1', total_amount: '10.00' }] })
  assert.match(html, /手牌\s*001/)
  assert.match(html, /非收款凭证/)
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
})
```

- [x] **Step 2: 运行** `node --test electron/service-receipt.node-test.cjs` 和 `npm.cmd exec -- vitest run src/domain/receipts/printing.test.ts src/composables/useVisitOrdering.test.ts`。
- [x] **Step 3: 接入原 IPC，不增加宽泛的 Node/文件权限。** 58mm、54mm 内容宽度、突出 24px 以上的手牌标识、开单员工姓名/账号、创建时间、本次条目和金额；补打标识来自该类型任务次数。共享转义辅助函数，但不让两种模板的对象字段混用。

```typescript
const result = retry ? await ordering.retryPending(target.visitId) : await ordering.submitSnapshot(target)
if (!isCurrent()) return
if (clearDraft) {
  ordering.drafts.clear(result.target.visitId)
  draftRevision.value++
  if (String(route.params.id) === result.target.visitId) consumptions.value = {}
}
// 业务成功先更新页面，打印失败不得重新抛为 addSelectedItems 失败。
if (result.servicePrintJob) {
  const print = await printServiceJob(result.servicePrintJob.id, 'automatic',
    auth.terminal?.printer_name || localStorage.getItem('xiquan_printer_name') || undefined,
    businessGeneration.capture())
  if (print.state === 'failed' || print.state === 'uncertain') ElMessage.warning(print.message)
}
```

实际调用前以业务 generation 核对当前主体；开始尝试确认 print_allowed 后调用 `window.xiquan.printReceipt`，结果写对应尝试 endpoint。断网导致结果不确定只提示补打页核对，不自动重新打印；浏览器返回明确“下单成功，请在桌面端打印”。所有结果路径使用 busy release 的 finally，切换账号后的旧响应不得操作新主体。
- [x] **Step 4: 回归模板、下单与原结账打印。** 加单数据重复/接口重试、打印拒绝、尝试结果超时、退出登录和页面切换均不再下单；未服务岗位和无 meta 响应不调用打印。`npm.cmd run type-check`，`node --test electron/*.node-test.cjs`，相关 Vitest；真实 XP-58 的纸张、中文和切纸行为在用户本机验收，自动测试不冒充实机。
- [x] **Step 5: 提交** `feat(printing): print scoped staff submission slips on local 58mm printers`。

执行证据：缺失模板/打印 helper 与返回 meta 的红灯后，66 项 Electron Node 测试、40 项相关 Vitest 和 type-check 通过。实际 View 测试验证 USB 失败仍只有一笔订单请求。实体打印机未在本轮连接验收。

## Task 6: 两类当日补打 UI、午夜过期和有限清理

**Files:**
- Create: `server/tests/test_receipt_retention050.py`、`client/src/domain/receipts/day.ts`、`day.test.ts`、`views/PrintJobsView.test.ts`。
- Modify: `server/app/receipt_retention.py`、`database_guards.py`、`receipt_service.py`、`api/checkout.py`、`api/service_print.py`、`server/run.py`、`client/src/views/PrintJobsView.vue`、`navigation/menu.ts`、`navigation/access.ts`、`router/index.ts`、相关测试。

**Interfaces:**
- Consumes: Task 4 的 `business_day_bounds`、`next_midnight`、`require_current_receipt`。
- `cleanup_expired_receipts(now=None) -> {'order_jobs':int,'settlement_jobs':int}`；`start_receipt_cleanup(app) -> None`，不自动迁移，不把异常扩散成 API 启动失败。
- `cleanup_expired_receipts_with_owner(connection, now: datetime, batch_limit: int=100) -> dict[str,int]`：在短暂独占写屏障下，只处理四张小票表的精确过期 DELETE，不释放或修改正在进行的重置/维护状态。
- UI 读取 `service_receipt_reprint`、`settlement_receipt_reprint`；原 `receipt_reprint` capability 保留兼容，两者至少一个才有 print-jobs 页面。

- [x] **Step 1: 日期边界与类型视图写红灯。**

```python
from datetime import datetime, timezone
def test_shanghai_natural_day_is_not_rolling_24_hours():
    from app.receipt_retention import business_day_bounds
    start, end = business_day_bounds(datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc))
    assert start == datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
```

UI 测试挂载 PrintJobsView：最高权限显示两个 tab，cashier 只有结账，male_scrubber 只有下单；成功状态有补打按钮；依次延迟两个列表响应，旧响应不能覆盖新 tab。
- [x] **Step 2: 运行** `& '.\.venv\Scripts\python.exe' -m pytest tests/test_receipt_retention050.py -q` 和 `npm.cmd exec -- vitest run src/views/PrintJobsView.test.ts src/domain/receipts/day.test.ts`，确认旧实现不符合。
- [x] **Step 3: 实现日期和清理核心。** 固定 UTC+8 算北京时间边界，可使用 ZoneInfo('Asia/Shanghai')（本机缺 timezone 数据时采用同一固定 UTC+8，不能用本地系统时区）。GET/详情/开始尝试/写结果全部使用同一界限，过期任务不重新创建。先删过期尝试再删所属任务，只使用明确四张小票表，绝不 DELETE 金融/审计/认证证据表。

```python
from datetime import datetime, timedelta, timezone

def business_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError('Receipt time must be timezone-aware')
    china = timezone(timedelta(hours=8), 'Asia/Shanghai')
    local = now.astimezone(china)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)

def next_midnight(created_at: datetime) -> datetime:
    return business_day_bounds(created_at)[1]
```

经营期间 guard 默认会禁止删除旧期间行，不能只提供一个无法实际删除的 owner 入口。仅对 `print_jobs`、`service_print_jobs`、`settlement_print_attempts`、`service_print_attempts` 的 DELETE 定向授权过期清理：必须是真正数据库及目标表 owner 登录、持有独占写屏障、任务首次创建时间早于北京时间今日起点；尝试记录以父任务日期判断。SQLite 测试用私有 connection.info 对应受控清理上下文；不能让 API 请求、GUC 或 SET ROLE 自称 owner。当前期间其他检查、所有非小票表 guard、金融和审计防改保持原样。后台使用原维护连接、每批至多100个任务，维护/重置中不抢占；午夜及重启补清理全期间过期小票，不采用等下次人为维护才删除的方案。客户端按服务器 expires_at、切换前台和实时事件刷新；跨午夜已在系统队列的纸张不承诺撤回。
- [x] **Step 4: 实现列表和补打。** 当前日所有三状态可分页（每页 10）；最高权限两 tab 各自分页/加载，普通岗位不显示不可用类型。服务小票提示非收款凭证，结账保持已收款。按 Task 5 helper 打印，对应类型结果更新，过期响应清空并提示。状态代码不再把 success 显示为“待打印”。保留旧数组列表形式，显式 paged/status 才走新版对象。
- [x] **Step 5: 验证并提交。** 覆盖超过 100 条、23:59:59/00:00:00、时区不同、停机恢复、补打不延长有效期、跨午夜结果、不创建过期任务、财务/会员/库存/幂等/审计计数不减少。`& '.\.venv\Scripts\python.exe' -m pytest tests/test_receipt_retention050.py tests/test_receipt_permissions050.py -q`；上述 Vitest/type-check。提交 `feat(receipts): isolate daily reprint views and expire receipt data safely`。

实现安全细化：生产定时清理使用独立无端口、仅 backend 网络的 receipt-cleanup 服务（Task 7 接入）。API 不注入 MAINTENANCE_DATABASE_URL，保留原受限身份；独立任务使用原所有者连接。SQLite 测试使用仅受控连接可设置的 cutoff；SQL 只授权过期小票 DELETE，创建时间和身份快照不可改。43 项相关后端测试、14 项 UI/日期/导航测试及 type-check 已通过，实体 PG17 证明由部署隔离副本执行。

## Task 7: PostgreSQL 17、备份权限及可恢复云端部署

**Files:**
- Create: `deploy/cloud/scripts/desktop_050_guard.py`、`desktop_050_deploy.py`、`scripts/invoke-desktop-050.ps1`、`scripts/desktop-050-deploy-entry.ps1`。
- Modify: `deploy/cloud/scripts/runtime-role.sql`、`reset-role.sql`、`backup-role.sql`、必要的原备份/结构预检模块（保持旧脚本接口）。
- Test: `scripts/tests/test_desktop_050_guard.py`、`test_desktop_050_entrypoints.py`、`test_desktop_050_recovery.py`。

**Interfaces:**
- OLD `20261008_registration_token`；HEAD `20261011_service_receipts`。
- Stage `/opt/xiquan-releases/desktop050-stage-[0-9a-f]{32}`；job `/opt/xiquan-backups/desktop050-cutover-[0-9a-f]{32}`。
- PS 参数：Mode `preflight|deploy|resume|all`、BundlePath、ExpectedSha256、SourceCommit、Stage、Job、EcsTarget（默认 root@39.96.217.210）、StageOnly。
- 新检查点包含源哈希、commit、确切镜像、迁移结果、后备份验证、ready、服务健康和 completed；部署成功不等于客户端已发布。
- `compare_retained_rows(before_tables: dict, after_tables: dict, names: tuple[str,...]) -> None` 先核对指定表 rows/sha256；`compare(before,after)` 在此基础上额外核对完整 schema、身份回填、账号白名单、外键、权限及所有者。

- [x] **Step 1: 先写协议、快照保持及失败检查点测试。**

```python
def test_compare_rejects_any_financial_or_audit_row_change():
    from desktop_050_guard import compare_retained_rows
    from stock_guard import GuardError
    import pytest
    before = {'schema': '20261008_registration_token', 'tables': {
        'audit_logs': {'rows': 2, 'sha256': 'a'}, 'payments': {'rows': 1, 'sha256': 'b'}}}
    after = {'schema': '20261011_service_receipts', 'tables': {
        'audit_logs': {'rows': 2, 'sha256': 'changed'}, 'payments': {'rows': 1, 'sha256': 'b'}}}
    with pytest.raises(GuardError):
        compare_retained_rows(before['tables'], after['tables'], ('audit_logs', 'payments'))
```

guard 文件测试导入沿用 scripts/tests 现有 sys.path 插入 deploy/cloud/scripts 的方式，不隐式依赖系统模块。增加“员工只允许精确删除原软删除非保护账号”“全部不可变原行哈希不变”“元数据增加不能要求所有表完全相同”的实际 PostgreSQL 隔离用例。
- [x] **Step 2: 红灯运行与 PS5.1 Parse 验证。** `& '.\.venv\Scripts\python.exe' -m pytest '..\scripts\tests\test_desktop_050_guard.py' '..\scripts\tests\test_desktop_050_recovery.py' -q`。所有中文 PS 文件写 UTF-8 BOM，使用 Parser.ParseFile，错误必须为 0。
- [x] **Step 3: 实现新 gate 而非借用旧版本 ready。** 快照允许新增身份/小票表、外键改变及已批准软删除清理，其他既有业务/审计行原样；保持所有最高管理员、手机号与策略版本。新表 runtime 必要 DML 列授权，历史身份/安全证据不可 UPDATE/DELETE/TRUNCATE；backup 对全 schema/序列只读并在迁移后验证可 pg_dump。

```python
from stock_guard import require

def compare_retained_rows(before_tables: dict, after_tables: dict,
                          names: tuple[str, ...]) -> None:
    for name in names:
        require(name in before_tables and name in after_tables, 'Retained table missing: ' + name)
        before, after = before_tables[name], after_tables[name]
        require(before['rows'] == after['rows'] and before['sha256'] == after['sha256'],
                'Retained data changed: ' + name)
```

完整 compare 必须使用真实快照，额外核对原业务列元数据与 FK 精确允许列表，不能因为这个纯行比较测试通过就跳过结构及权限核对。

```powershell
$delivery = Get-Content -LiteralPath '.\最新版安装包-账号与小票-0.5.0\delivery-manifest.json' -Raw | ConvertFrom-Json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\invoke-desktop-050.ps1' `
    -Mode preflight -BundlePath $delivery.SourceBundle -ExpectedSha256 $delivery.SourceSha256 `
    -SourceCommit $delivery.SourceCommit -EcsTarget 'root@39.96.217.210'
# all 模式自动解析上述唯一 JSON stage，不能再要求用户手打随机路径。
```

复用有界传输实现，所有小/大上传有超时、进度和 SHA256。离线镜像复用已验证本地依赖，clone restore 256MiB、maintenance 384MiB、reserve 128MiB 按实际并行阶段算资源，不使用固定 2GiB 门槛；不清 Docker 运行资源来过门槛。生产备份及隔离恢复先完成，迁移后再备份并恢复核验，才切换应用。

健康探针使用 `curl --http1.1 --fail --show-error --max-time 20 --resolve api.pqxqxy.xyz:443:127.0.0.1`，保留真实域名/TLS，不用 `-k`；重建 API 后 nginx test+reload，并独立验证 API 与静态页面。后台小票清理在拥有维护时不抢写；恢复 reset worker 与原 API 配置，不修改密钥/真实 `.env` 或临时把旧 head 当新 head。

恢复分阶段：迁移前可复用已构建镜像；迁移完成但后备份未验证只能补验证，不再次迁移；ready 后仅启动验证确切新镜像；maintenance 已释放只能做最终健康核验和 completed，不重新挂维护或恢复旧数据库。失败保留精确 command evidence，不打印含密钥参数的原始命令。
- [x] **Step 4: 隔离演练和本地回归。** PG17 真正测试 runtime 不可改审计/凭证、backup 全库可读、当前账号删除/再注册、两类打印权限/跨午夜。若本机没有 Docker/PG17，将演练放入用户部署脚本内独立容器，不虚称本机已完成。更新脚本测试使用 fake subprocess，不 SSH 生产。运行 Python 全部相关测试、脚本测试及 PS parse。
- [x] **Step 5: 提交** `feat(deploy): add recoverable 0.5.0 identity and receipt cutover`。

Task 7 本地证据：17 项 guard/recovery/entry 协议测试和2项旧 head 迁移回归通过；PS5.1 parse 无错误；源码安全扫描通过。隔离恢复256MiB、所有者命令256MiB、余量128MiB，恢复峰值640MiB；镜像探针384MiB，单独预算512MiB。实体 PG17 证明内置在用户部署的隔离副本 gate，本机没有 Docker，未执行云端。备份、迁移、客户端发布仍需执行。

## Task 8: 0.5.0 更新构建、签名发布与交付指令

**Files:**
- Create: `scripts/build-desktop-050.ps1`、`sign-desktop-050.ps1`、`desktop-050-publish-entry.ps1`、`scripts/lib/desktop-050.cjs`、`desktop-050.node-test.cjs`、`docs/releases/2026-10-11-desktop-050.md`。
- Modify: `client/package.json`、`client/package-lock.json`；必要的源构建 allowlist/兼容 verifier。
- Test: `scripts/tests/test_desktop_050_source.py`、`test_desktop_050_entrypoints.py`；原 `client/electron/updater-guard.node-test.cjs` 和 `scripts/lib/windows-*.node-test.cjs`。

**Interfaces:**
- build 参数 PublicKeyPath、OfflineRuntimeCache、BuildId、OutputDirectory、DryRun；必须 frozen committed source。
- 交付 JSON 包含 Version、Targets、SourceCommit、SourceBundle、SourceSha256、ReleaseRoot、OutputDirectory、CloudChanged、UpdateSignature。
- 签名原私钥默认 `F:/溪泉洗浴系统/private/溪泉发布密钥/desktop-release-private.pem`；不读取/输出私钥到聊天，不用已搬走的 F:/溪泉发布密钥。
- 交付 `01-部署云端.ps1`、`02-签名并发布桌面更新.ps1`、`完整PowerShell指令.md` 和实际 EXE/source ZIP/hash 清单；无新增 Android 构建脚本。
- `scripts/lib/desktop-050.cjs` 导出冻结的 `releaseVersion`、`releaseNotes`、`targets` 和原 `trust`（由 operations-release.cjs 导入）；signingPlan 接口复用 desktop-045.cjs，不重新生成信任根。

- [x] **Step 1: 写源版本、目标、原信任及日志测试。**

```javascript
const test = require('node:test')
const assert = require('node:assert/strict')
const candidate = require('./desktop-050.cjs')
const { trust: originalTrust } = require('./operations-release.cjs')
const notes = [ '优化主登录页面', '新增账号密码修改功能',
  '新增搓澡师下单打印小票的功能', '新增每天小票补打的功能' ]
test('0.5.0 delivery preserves exact targets, notes and original trust', () => {
  assert.equal(candidate.releaseVersion, '0.5.0')
  assert.deepEqual(candidate.releaseNotes, notes)
  assert.deepEqual(candidate.targets, ['win10-x86', 'win10-x64', 'win11-x86', 'win11-x64'])
  assert.deepEqual(candidate.trust, originalTrust)
})
```

- [x] **Step 2: 先运行脚本/源红灯，后 bump package 及 lockfile 的唯一版本字段。** 不 npm update、不升级 Electron。执行 `build-desktop-050.ps1 -DryRun` 前验证冻结源、四目标、公钥和本地已校验 runtime cache；下载失败保留原文件且不发布。
- [ ] **Step 3: 构建与源包交付。** npm build 完成 type-check，写准确四条日志到网页版本清单；build-operations-source 从已提交文件生成 source manifest，不带 `.env`、private、DB、旧 APK/EXE。用 cloud-archive 的 PortableEntryNames，规避 Windows ZIP 路径及占用锁。只复制实际生成的四 EXE，记录 SHA256；缺任何目标立即停止，不用其他版本冒名。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\build-desktop-050.ps1'
$deliveryFolder = 'F:\溪泉洗浴系统\最新版安装包-账号与小票-0.5.0'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $deliveryFolder '01-部署云端.ps1')
if ($LASTEXITCODE -ne 0) { throw '云端步骤未完成，停止发布桌面更新' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $deliveryFolder '02-签名并发布桌面更新.ps1')
if ($LASTEXITCODE -ne 0) { throw '桌面更新未发布，保留输出和原安装包' }
```

发布脚本要求确切 0.5.0 cloud completed 回执而非仅“确认已成功”文字；读取线上原签名策略，沿用 minimum_version，计算大于线上序号的新 sequence，核验候选后原密钥签名。先上传版本资产核 SHA/可读性，再原子切换策略，保留旧包。不猜 sequence=1，不用未签名 fallback。
- [ ] **Step 4: 完成组合验证。** `npm.cmd run build`、client Vitest/Electron tests、server pytest、scripts pytest、Windows signer/publisher本地fixture及PS解析。登录页0.4.9/0.4.8更新解析回归原trust，实机覆盖测试由用户确认，不模拟成真实测试结果。完整文档区分“源码/包已构建”“云端已部署”“更新已签名并发布”状态。
- [x] **Step 5: 提交** `release: prepare 0.5.0 signed desktop delivery and complete PowerShell workflow`，冻结 HEAD 后构建最新 SOURCE 与正式包，不能把包引用指向前一提交。

Task 8 本地收尾证据：桌面59文件/246项Vue测试、123项Electron/构建/签名发布/归档与源码安全Node测试通过；170项脚本Python测试在Windows PowerShell 5.1环境通过（直接从PS7继承模块路径会使旧049测试找不到Get-FileHash，不更改安全校验来绕过）。手机37文件/210项测试通过。一次完整后端回归先发现10处旧断言/本地SQLite兼容问题；定位后48项对应回归通过，最终完整后端755项通过、1项实体PG17测试明确跳过（本机无Docker），591.35秒。四个现代通道将同时更新旧x64入口，保留Win7和手机策略。首轮实际四包/SOURCE构建通过；收尾发现归档ZIP流读取不能完整结束及路径斜杠不一致循环，已改为Windows内置完整有界ZIP读取、允许核实哈希一致的中断副本续准备，相关新增红灯/绿灯通过。冻结新提交后重新构建四包/SOURCE，真实最终哈希写入交付目录。签名、云端及实机验收仍由用户按完整指令完成。

## Task 9: 版本归档、核实后精确清理与最终交付

**Files:**
- Create: `scripts/archive-desktop-050.ps1`、`scripts/lib/archive-proof.cjs`、其 node tests；`docs/releases/archive-050.md`；归档仓库中的版本索引与 manifests（在检查现有布局后沿用）。
- Preserve: 当前源码/迁移、原 `.git`、private 密钥/私密证据、当前运行时缓存、新交付目录及预先存在的三个未跟踪文件。

**Interfaces:**
- archive 模式 `plan|verify|clean`，plan 只读列出精确旧文件，verify 验证远端证据，clean 仅消费新鲜完整 proof。
- proof 每文件 `{version,sourceCommit,absolutePath,size,sha256,remoteUrl,remoteSha256,verifiedAt}`；一项缺失/哈希变更/链接指向错误仓库即不清理该项。
- `eligibleCleanup(entry, proof: {repository:string,entries:array}, options: {root:string,now:Date}) -> entry`；只核对证据和路径策略，不删除文件。Node tests 在 `scripts/lib/archive-proof.node-test.cjs`；PowerShell 调用 verifier 后自行检查真实文件/reparse/大小/哈希才逐项删除。

- [x] **Step 1: 写危险路径/未归档证明红灯。**

```javascript
const test = require('node:test')
const assert = require('node:assert/strict')
const { eligibleCleanup } = require('./archive-proof.cjs')
const now = new Date('2026-10-11T04:00:00Z')
const root = 'F:\\溪泉洗浴系统'
const entry = { version:'0.4.9', sourceCommit:'a'.repeat(40),
  absolutePath:root + '\\release\\Xiquan-Bathhouse-Setup-0.4.9-win11-x64.exe',
  size:100, sha256:'a'.repeat(64), remoteSha256:'a'.repeat(64),
  remoteUrl:'https://github.com/Rasmus911/xiquanxiyu/releases/download/desktop-v0.4.9/Xiquan-Bathhouse-Setup-0.4.9-win11-x64.exe',
  verifiedAt:now.toISOString() }
const proof = { repository:'https://github.com/Rasmus911/xiquanxiyu', entries:[entry] }
test('cleanup requires matching fresh proof and a permitted individual file', () => {
  assert.deepEqual(eligibleCleanup(entry, proof, {root, now}), entry)
  for (const absolutePath of [root, root + '\\private\\key.pem', 'F:\\other-project\\old.exe']) {
    assert.throws(() => eligibleCleanup({...entry, absolutePath}, proof, {root, now}))
  }
  assert.throws(() => eligibleCleanup({...entry, sha256:'b'.repeat(64)}, proof, {root, now}))
  assert.throws(() => eligibleCleanup(entry, {...proof, entries:[]}, {root, now}))
})
```

- [x] **Step 2: 测试 proof 核验，生成归档计划。** 执行 `node --test scripts/lib/archive-proof.node-test.cjs`。按实际目录识别旧安装包、交付源 ZIP、版本专用说明及旧交付目录，逐个列出文件，不把当前必要源码/完整历史迁移链/共享构建脚本/cache 判为冗余。解析路径必须位于本项目精确候选范围，拒绝 reparse point、目录根、private、未知文件和宽泛递归目标。证明最长有效24小时，clean 前再次取远端核对，发生本地/远端变化即保留。
- [ ] **Step 3: 做版本分类并上传。** 源码和版本索引从 Git 可追溯提交归档；安装包及 ZIP 作为版本 Release 资产，普通 Git 大文件预检以 90MiB 为保守上限。扫描归档内容和历史已暂存变更，任何密钥/配置/数据库/会员资料拒绝进入公开仓库。打开用户指定 GitHub Desktop，选择确切 https://github.com/Rasmus911/xiquanxiyu 仓库 Push；无法控制界面则提供精确用户操作并保留源文件。只有真正完成 push/Release 上传并核对后，才能填写 verifiedAt。
- [ ] **Step 4: 核验后清理每个精确文件。**

```powershell
# $entry 必须先经过 archive-proof 核对远端、版本、大小、SHA256 和绝对路径。
$resolved = (Resolve-Path -LiteralPath $entry.absolutePath).Path
if ((Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.sha256) {
    throw '本地文件已经变化，保留不删除'
}
Remove-Item -LiteralPath $resolved -Force
# 空的旧交付目录仅在检查确实为空后非递归删除，禁止 Remove-Item 项目根 -Recurse。
```

不能把 Git 分支上的本地 commit 或“上传准备好”写成已归档；私密备份不上传，保留并说明其作用。清理失败不会删其它未知文件，也不会继续宽泛 prune。提供实际远端提交/Release、删除文件及可恢复来源清单。
- [ ] **Step 5: 最终核验及交付。** 查看最新交付目录实际文件/哈希、git status、已验证归档范围；报告真实构建/发布/实机验收状态，未部署时只给本机 PowerShell指令不称已上线。原用户文件保持原样。提交 `docs: record verified 0.5.0 delivery and version archive scope`。

## 全局覆盖与停止条件

Spec §3 → Tasks 2–3；§4 → Task 1；§5 → Tasks 4–5；§6–7 → Tasks 4–6；§8 → Tasks 7–9；§9 验收分布在每个任务 Step 4/5。所有任务共享原签名、三端旧功能、历史金额、审计及保密约束。

不得因用户赶时间去关闭权限、签名、TLS 或审计保护。只跑与任务相关的红绿测试及一次必要全局回归，不反复无意义全套测试。云端实际操作或 GitHub 界面需要用户参与时给出单一完整入口及真实阶段，不重复发送互相冲突的旧脚本。缺失源提交、确切原密钥、部署 completed、资源/备份验证或远端归档证据时保留材料，说明缺项，不编造成功。

执行中：Tasks 1–7 已实施并验证；安装包与源ZIP在冻结本提交后实际构建。实体 PG17 演练在用户执行部署时于隔离副本运行，本机没有 Docker。归档计划识别508项旧材料，已读取GitHub main提交574233e1a0dfe33bb7659a7888cc263967f22267；网络读取失败期间全部保留，没有删除。GitHub Desktop快捷方式已尝试打开但没有可控制窗口，必要时由用户完成Commit/Push，随后脚本只清理已核实远端文件。当前源码/原Git历史/私有密钥/仍被引用的旧部署基类不是冗余。真实构建和最终归档结果保存在交付/私有回执，不宣称已经部署、签名或上传。
