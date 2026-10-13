# 0.5.1 实体会员卡与历史更新日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 D5 实体卡开户、绑定/补卡、储值及次卡结账，增加登录页可滚动历史日志，并交付可由旧桌面在线覆盖更新的 0.5.1。

**Architecture:** 实体卡只索引现有会员账户；卡绑定历史与结账抵次关联使用独立、按经营期间隔离的表。金额支付、扣次、返次、审计在既有财务事务中完成。历史日志内置于安装包，更新日期只接受可核实的发布记录；发布沿用原信任链，云端使用扩展迁移和确切检查点恢复。

**Tech Stack:** Vue 3、Element Plus、TypeScript、Electron、Flask、SQLAlchemy/Alembic、PostgreSQL 17、pytest、Vitest、Node test、PowerShell 5.1、Docker Compose。

**Spec:** `F:\溪泉洗浴系统\docs\superpowers\specs\2026-10-12-desktop-051-physical-membership-design.md`，包含已确认的第 11 节历史日志要求。

## Global Constraints

- 项目根目录 `F:\溪泉洗浴系统`；实现前 HEAD 为 `ead2276`，不覆盖用户已有未提交文件。
- 桌面版本 `0.5.1`；目标仅 `win10-x86,win10-x64,win11-x86,win11-x64`，不构建 Win7。
- 正式 0.5.1 更新日志仅 `1. 增加实体卡消费功能`。
- 原应用 ID `com.xiquan.bathhouse`、原信任公钥及 key ID `b26477a9ed540ad0` 不变；保留已有最低版本和发布序号单调校验。
- 卡号为 1–64 位 ASCII 数字文本；保留前导零，D5 示例 `315346091` 后 Enter；Enter 只结束读取，不能提交资金操作。
- 无手机号在数据库保存 NULL，API 的 `phone` 仍返回字符串，无手机号为 `""`。
- 次卡 1 次只抵所选 1 人的独立有效门票；不抵服务/商品，不重复抵套票已覆盖的票，不先核次后另发结账请求。
- 原订单及结算原消费金额不变；`paid_amount = total_amount - pass_redemption_amount`。核次不是新的现金流，购卡款不重复入账。
- 不清空现有账户、会员、余额、次数、订单、库存、审计或令牌；经营重置仍遵循原经营期间规则。
- 手机沿用当前 1.2.9/code 16 和既有权限。本次不扩展手机 USB 读卡、收银或会员页面；只有确需兼容修复才新建同证书 APK。
- ECS `root@39.96.217.210`；目录 `/opt/xiquan/xiquan/deploy/cloud`；API `https://api.pqxqxy.xyz/api`。
- 前置 schema `20261011_service_receipts`；目标 schema `20261012_physical_membership`；禁止向旧 schema 回退启动旧 API。
- 小内存部署采用隔离维护/恢复容器各 256 MiB、预留 128 MiB，逐阶段核查实际可用内存；不能重新使用 2 GiB 门槛。
- 小票清理服务使用 256 MiB、标准库心跳健康检查；保留北京时间自然日、两类小票隔离与最高权限可见规则。
- 历史日志从 0.4.7 到 0.5.1，倒序；缺少发布证据显示“发布日期未核实”，未发布的 0.5.1 显示“待发布”。
- 不上传任何私钥、`.env`、真实数据库、会员资料、密码或私有恢复证据。必要私有文件、`.git`、完整迁移链和共享脚本必须保留。
- 历史公开文件通过用户指定 GitHub Desktop 上传到 `https://github.com/Rasmus911/xiquanxiyu`；核实远端文件字节后才能逐文件清理。普通 Git 文件上限采用 90 MiB 安全线，分片各 32 MiB。
- 所有本地改动用 apply_patch；测试只用隔离数据库。生产部署由用户运行交付 PowerShell，不自动重置或恢复生产。

---

## 文件边界与共享接口

以下路径均相对项目根目录，执行命令使用相应工作目录。

| 职责 | 新文件 | 现有集成点 |
| --- | --- | --- |
| 卡身份、绑定约束 | `server/app/member_card_models.py`, `server/app/member_cards.py` | `models.py`, `serializers.py`, `database_guards.py` |
| 实体卡开户与补卡 API | `server/app/api/member_cards.py` | `api/__init__.py`, `api/members.py`, 现有短信/幂等服务 |
| 次卡抵门票与退款 | `server/app/pass_billing.py`, `server/app/member_payment.py` | `api/checkout.py`, `financial_integrity.py`, `api/reports.py` |
| 局部读卡和开户 UI | `client/src/components/members/CardScanDialog.vue`, `PhysicalMemberDialog.vue`, `MemberCardBindingDialog.vue` | `MembersView.vue`, `MemberDetailDrawer.vue`, `types.ts` |
| 支付会员选择 | `client/src/components/checkout/MemberPaymentSelector.vue` | `CheckoutView.vue`, `domain/checkout/checkout-request.ts`, `PaymentPanel.vue` |
| 历史日志 | `client/src/update/history-data.json`, `release-history.ts`, `components/update/ReleaseHistory.vue` | `UpdateCenter.vue`, Electron updater 状态、`env.d.ts` |
| 扩展迁移 | `server/migrations/versions/20261012_physical_membership.py` | 期间/屏障触发器及最小数据库角色授权 |
| 云端门禁与恢复 | `deploy/cloud/scripts/desktop_051_guard.py`, `desktop_051_deploy.py`, `scripts/invoke-desktop-051.ps1` | 共享备份、PG17 隔离恢复、HTTP/1.1 字节验证 |
| 发布、归档 | `scripts/lib/desktop-051.cjs`, `build-desktop-051.ps1`, `sign-desktop-051.ps1`, `desktop-051-publish-entry.ps1`, `archive-desktop-051.ps1` | 现有四目标构建、原签名、远端归档证明 |

API 扩展协议固定如下；后续任务不得自行改名：

```ts
type MembershipType = 'stored' | 'pass'
interface PhysicalOpenRequest {
  card_uid: string; phone: string | null; holder_surname: string | null
  surname_confirmed: boolean; membership_type: MembershipType
  amount: string; count?: number; pass_name?: string; valid_until?: string | null
  payment_method: 'cash' | 'wechat' | 'alipay'; idempotency_key: string
}
interface CardBindingRequest {
  card_uid: string; password: string; idempotency_key: string
}
interface PassUseSelection { member_pass_id: string; visit_ids: string[] }
interface MemberVerification {
  method: 'phone' | 'card'; card_binding_id?: string; surname_confirmed: boolean
}
interface CheckoutBenefits {
  pass_use: PassUseSelection | null; member_verification: MemberVerification | null
}
```

- `POST /api/members/physical-open`：整个已确认收款开户，201；同键同请求重试 200，返回同一 `member`、`card_binding`、`member_pass`（储值时 null）。
- `POST /api/members/<member_id>/physical-card`：核对当前员工密码后绑定或补卡，200，返回会员及新有效绑定。
- `GET /api/members/lookup?phone=...` 或 `?card_uid=...`：必须二选一，返回既有会员字段及 `card_binding`、`passes`，不得匿名识别。
- `POST /api/checkout/preview` 和 `/complete`：保留旧请求，新增 `pass_use`、`member_verification`；预览新增 `pass_redemption_amount`、`pass_redemption_count`、`amount_due`、`pass_redemptions`。
- 结算响应新增相同抵次汇总；收据新增抵次明细与货币应付。未知新字段不能改变旧请求金额含义。
- `CardScanDialog` 的 props 为 `modelValue:boolean, busy?:boolean, error?:string`，事件为 `update:modelValue(boolean)`、`read(cardUid:string)`；不暴露资金提交事件。

## Task 1：卡号模型、空手机号及数据库保护

**Files:** Create `server/app/member_cards.py`, `server/app/member_card_models.py`, `server/migrations/versions/20261012_physical_membership.py`, `server/tests/test_member_card_models051.py`。Modify `server/app/models.py`, `serializers.py`, `database_guards.py`。

**Interfaces:** `normalize_card_uid(value: str) -> str`；`MemberCardBinding` 表名为 `member_card_bindings`，字段为 `member_id, card_uid, is_active, created_by, terminal_id, revoked_at, replaced_by_id`，另含 PeriodMixin/TimestampMixin；`SettlementPassRedemption` 表名为 `settlement_pass_redemptions`，字段为 `settlement_id, visit_id, order_item_id, member_pass_id, count, amount`，另含 PeriodMixin/TimestampMixin；`Member.holder_surname` 为可空 String(40)。

- [ ] 写 `test_member_card_models051.py` 的首个失败测试及模型约束测试：

```python
import pytest
from app.member_cards import normalize_card_uid

@pytest.mark.parametrize('raw, expected', [
    ('315346091\r\n', '315346091'), (' 000315346091\n', '000315346091')])
def test_uid_is_text(raw, expected):
    assert normalize_card_uid(raw) == expected

@pytest.mark.parametrize('raw', ['', '1 2', '１23', '1' * 65, 315346091])
def test_uid_rejects_invalid_input(raw):
    with pytest.raises(ValueError):
        normalize_card_uid(raw)
```

- [ ] 在 server 运行 `& '.\.venv\Scripts\python.exe' -m pytest tests/test_member_card_models051.py -q`，确认因新模块缺失而失败；保存简短输出。
- [ ] 实现标准化，不把卡号转数字，不删除内部字符：

```python
import re

def normalize_card_uid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('卡号必须是数字文本')
    uid = value.strip()
    if not re.fullmatch(r'[0-9]{1,64}', uid):
        raise ValueError('卡号应为1至64位数字')
    return uid
```

- [ ] 创建模型；卡号使用 `(period_id, card_uid)` 全状态唯一，有效绑定增加 `(period_id, member_id)` 条件唯一索引（Postgres/SQLite 均支持 `is_active` 条件）。失效卡不可重分配；返次不删除原抵次行。
- [ ] 扩展迁移仅放宽 phone nullable、加 holder_surname、创建上述两表/索引。迁移 revision/down_revision 使用全局约束值；新表装配期间/屏障触发器。将抵次表加入 append-only；卡绑定保护 period/member/card/创建身份及时间，只允许停用、替换引用及版本变更。
- [ ] runtime 角色仅允许必要 SELECT/INSERT 和卡撤销状态 UPDATE；backup 角色可以读两表；禁止 runtime DELETE/TRUNCATE/改抵次金额。沿用已有角色函数，不给普通 API 所有者凭据。
- [ ] `member_dict` 用 `item.phone or ''`；返回独立 holder_surname、有效 card_binding。修复纯姓名搜索不能因空数字查询命中全表；无手机号不调用 `.replace` 的空值分支。
- [ ] 添加并运行空手机号多会员、真实手机号重复、重复卡号、两张有效卡、跨期间查找、不可更改抵次金额测试。SQLite 测试不能代替 PG17 授权/并发证明，实际 PG 证明放 Task 7。
- [ ] 运行本任务测试至全绿，`git diff --check`；只提交本任务文件：`git add server/app/member_cards.py server/app/member_card_models.py server/app/models.py server/app/serializers.py server/app/database_guards.py server/migrations/versions/20261012_physical_membership.py server/tests/test_member_card_models051.py`，`git commit -m "feat: add period-scoped physical membership card models"`。

## Task 2：已收款实体卡开户、识别、补卡和通知

**Files:** Create `server/app/api/member_cards.py`, `server/tests/test_member_card_api051.py`。Modify `server/app/api/__init__.py`, `api/members.py`, `member_cards.py`, `serializers.py`；已有短信服务只做可选手机号兼容。

**Interfaces:** 消费 Task 1 模型和卡号标准化、现有 `guard_financial_request`/`idempotency_lookup`/`idempotency_store`、真实 JWT 员工/终端及 member 权限。产出共享协议的三个端点；事务服务 `open_physical_member(employee, terminal, payload) -> dict`、`bind_physical_card(member, employee, terminal, payload) -> dict`（调用方提交事务）。

- [ ] 新增开户幂等失败测试：

```python
def test_paid_open_without_phone_is_atomic_and_idempotent(client, strict_owner_session):
    body = {'card_uid': '000315346091', 'phone': None, 'holder_surname': None,
            'surname_confirmed': False, 'membership_type': 'stored',
            'amount': '100.00', 'payment_method': 'cash',
            'idempotency_key': 'physical-open-051'}
    first = client.post('/api/members/physical-open',
        headers=strict_owner_session['headers'], json=body)
    assert first.status_code == 201, first.get_json()
    repeated = client.post('/api/members/physical-open',
        headers=strict_owner_session['headers'], json=body)
    assert repeated.status_code == 200, repeated.get_json()
    a, b = first.get_json()['data'], repeated.get_json()['data']
    assert a['member']['id'] == b['member']['id']
    assert b['member']['phone'] == ''
    assert b['member']['balance'] == '100.00'
    assert b['card_binding']['card_uid'] == '000315346091'
```

- [ ] 运行 `pytest tests/test_member_card_api051.py -q`（使用 server 虚拟环境），确认新端点 404 的失败。
- [ ] 用 `/members` 独立 blueprint 注册新路径；套用当前财务写序列化屏障/权限。金额 Decimal 且为正数；次卡 count 正整数、售价为真实正金额；收款方式仅 cash/wechat/alipay，不接受 balance 自充值。
- [ ] 开户一次事务写 Member + Binding + StoredValueLedger(recharge) 或 MemberPass + PassLedger(issue)，及审计/幂等结果。设置 surname 时要求 `surname_confirmed:true`；真实手机号已存在返回 409 `PHONE_EXISTS` 并提示先查询绑定，不自动合并。
- [ ] 返回原幂等结果的检查先于余额/卡号冲突检查；同键不同资料返回 409。失败 rollback 不留下会员、有效卡、余额、次数或“已收款”结果。不得把密码原文写入幂等响应/审计。
- [ ] 绑定/补卡锁定会员和相关卡；`verify_password(current_employee.password_hash, str(payload.get('password') or ''))` 使用既有密码校验方式。验证新卡后撤销旧卡并创建新卡；允许同键重试，不允许不同键重新启用旧卡。余额/次数不得改动。
- [ ] lookup 要求 phone/card_uid 恰好一个；按当前期间、未归档且启用会员识别，失效卡返回明确 `CARD_REVOKED`，未知卡 `CARD_NOT_FOUND`。返回当前可选次卡而不自动核销。
- [ ] 会员归档同事务停用绑定；发出 `members` 实时事件。仅实际有手机号才发送现有客户短信；管理员通知按既有配置执行。通知失败不得 rollback 已收款或自动再入账。
- [ ] 增加次卡售价/次数、姓核实、无手机号不发客户短信、同手机号双识别、错误本人密码、旧卡拒绝、权限 403、重复开户 rollback 测试；审计中文标签新增对应开户/绑卡/补卡名称。
- [ ] 运行新测试与 `tests/test_members_and_audit.py`；检查新增日志无密码，提交明确文件，commit：`feat: open and replace physical membership cards atomically`。

## Task 3：次卡抵门票、组合收款、返次及账目

**Files:** Create `server/app/pass_billing.py`, `server/app/member_payment.py`, `server/tests/test_pass_checkout051.py`, `server/tests/test_member_card_finance051.py`。Modify `server/app/api/checkout.py`, `financial_integrity.py`, `api/reports.py`, `serializers.py`, `client/electron/receipt.cjs`。

**Interfaces:** Task 1/2 卡绑定及会员；`TicketCandidate(visit_id:str, order_item_id:str, amount:Decimal, quantity:Decimal, covered_quantity:Decimal, status:str)`；`select_pass_tickets(tickets:list[TicketCandidate], visit_ids:list[str]) -> list[TicketCandidate]`。`prepare_pass_usage(visits, selection, member, *, lock:bool) -> PassUsage` 返回锁定的 MemberPass 或 None、票列表、抵次次数/金额；`record_pass_usage(settlement, usage, employee)` 和 `refund_pass_usage(settlement, employee, reason)` 不独立 commit。

- [ ] 首先写纯票据选择失败测试：

```python
from decimal import Decimal as D
import pytest
from app.pass_billing import TicketCandidate, select_pass_tickets

def test_pass_only_covers_uncovered_ticket_for_selected_visit():
    valid = TicketCandidate('v1', 'ticket1', D('15'), D(1), D(0), 'active')
    covered = TicketCandidate('v2', 'ticket2', D(0), D(1), D(1), 'active')
    assert select_pass_tickets([valid, covered], ['v1']) == [valid]
    with pytest.raises(ValueError):
        select_pass_tickets([valid, covered], ['v2'])
    with pytest.raises(ValueError):
        select_pass_tickets([valid], ['v1', 'v1'])
```

- [ ] 运行该文件确认新模块缺失；实现逐人恰好一条 active、quantity=1、covered_quantity=0、amount>0 的独立门票选择。订单候选仅从后端 `kind == 'ticket'` 生成，不按名字推断。
- [ ] preview 校验所选 visit 在当前结账范围内、次卡属于当前付款会员、未停用/未过期/次数充足；返回原总额、抵次、剩余金额；不写 PassLedger。
- [ ] complete 先返回既有幂等结果，再按固定顺序锁 visit、会员、绑定和 MemberPass；最终重查卡是否有效、姓是否确认、余次和余额。不信任客户端价格/角色，所有抵票金额从 OrderItem 得出。
- [ ] 同一事务扣次/写 checkout_consume(delta 负数、amount_paid=0)/写抵次行/收款/扣余额/关选中手牌/审计。支持全次卡抵票且 `payments:[]`、paid_amount=0；不插入虚假零现金 Payment。
- [ ] 金额规则具体实现为：

```python
original_total = sum((line.total_amount for line in active_lines), D('0'))
pass_amount = sum((ticket.amount for ticket in usage.tickets), D('0'))
amount_due = original_total - pass_amount
if sum((payment_amount for _, payment_amount in validated_payments), D('0')) != amount_due:
    raise ValueError('组合支付金额必须等于次卡抵扣后的应付金额')
# Settlement.total_amount 与 SettlementVisit.amount 保存原消费；paid_amount 保存 amount_due。
```

- [ ] 追加 HTTP 事务测试：正式门票15+搓澡10，使用1次后付10；两人门票只选择一人；儿童票按真实10抵；套票覆盖拒绝；余额不足另付现金；同键重试只有一个 consume；改 pass/visit/member/binding 同键拒绝；余额或次卡不足时订单、手牌、所有流水均不改变。
- [ ] 整单 refund 按原抵次关联恢复精确次数，写 checkout_refund(delta 正数、amount_paid=0)，不要求原次卡当前仍有效，不删除原核销；状态/幂等保护保证最多一次返次。退款失败全部 rollback。
- [ ] 财务核对新增 `total_amount == paid_amount + sum(redemptions.amount)`、核次/返次与抵次 count 一致。报表经营退款金额包括抵票面值，外部现金流仍仅原支付/购卡/充值，返次不是现金退款；保持原报表字段兼容。
- [ ] 58mm 结账收据显示原消费、次卡抵票次数/金额、剩余货币应付及组合付款，卡/姓文本用原 escaping；服务下单小票保持原规则。
- [ ] 运行新测试、`tests/test_mixed_checkout.py`、`tests/test_package_orders.py`、财务/退款已有测试和 Electron receipt Node tests。真实竞争测试在 Task 7 的 PG17 隔离库运行，不能声称 SQLite 已证明锁竞争。
- [ ] 只提交相关文件，commit：`feat: settle ticket passes and mixed payments in one transaction`。

## Task 4：局部读卡、实体开户与绑定界面

**Files:** Create `client/src/domain/members/card-input.ts`, `card-input.test.ts`, `components/members/CardScanDialog.vue`, `CardScanDialog.test.ts`, `PhysicalMemberDialog.vue`, `PhysicalMemberDialog.test.ts`, `MemberCardBindingDialog.vue`。Modify `types.ts`, `MembersView.vue`, `MemberDetailDrawer.vue`。

**Interfaces:** `normalizeCardInput(value:string):string|null` 与 Task 1 标准相同；共享 CardScanDialog props/events；Task 2 API。Member.phone 保持 string；新增 nullable holder_surname/card_binding，MemberPass 用明确字段类型而不是宽泛 Record。

- [ ] 写输入/Enter 事件失败测试：

```ts
import { expect, it } from 'vitest'
import { normalizeCardInput } from './card-input'

it('retains D5 text and rejects embedded whitespace', () => {
  expect(normalizeCardInput('000315346091\r\n')).toBe('000315346091')
  expect(normalizeCardInput('31 5346091')).toBeNull()
  expect(normalizeCardInput('３15346091')).toBeNull()
})
```

- [ ] client 运行 `npm.cmd exec -- vitest run src/domain/members/card-input.test.ts src/components/members/CardScanDialog.test.ts`，确认模块缺失失败。
- [ ] 实现标准化和模态框 focused ElInput：`@keydown.enter.stop.prevent="read"`、Escape 取消；仅 component-local listener，不监听 window 数字键。打开清空缓冲并 nextTick focus，关闭清空输入；busy 时忽略重复 Enter。
- [ ] 组件测试用真实 ElInput 发键盘事件，断言一次 read、父级支付 submit 未触发、关闭/重开无旧值、错误卡可重新输入；blur 不偷偷移焦抢占其他输入。
- [ ] MembersView 将原新增入口改“手机号开通会员”，增“实体卡开通会员”。两步对话框：资料/读取 → 现金微信支付宝收款确认；取消第二步不调用开户。可选姓有核实确认，次卡同时填次数/售价；无手机号安全显示“未留手机号”。
- [ ] 实体开户使用不可变 pending body/idempotency key；超时不生成第二键自动重发，提供原请求重试。结果只在当前弹窗 generation 有效时应用；成功刷新同一账户，不再发第二次充值或买卡请求。
- [ ] 详情根据绑定状态显示“绑定实体卡/补办实体卡”，读取新卡后密码弹窗，提交 current employee 密码；密码不存 storage、不放审计详情，关闭/成功/失败结束后清除输入。余额/次卡展示沿用既有页。
- [ ] 增加开户取消/无手机号/次卡价格/重复确认测试；执行新组件测试与会员 presentation 既有测试、`npm.cmd run type-check`。提交本任务文件，commit：`feat: add focused card scanning and physical member forms`。

## Task 5：结账刷卡、抵次选择与不确定请求保护

**Files:** Create `client/src/components/checkout/MemberPaymentSelector.vue`, `MemberPaymentSelector.test.ts`。Modify `client/src/views/CheckoutView.vue`, `CheckoutView.test.ts`, `components/checkout/PaymentPanel.vue`, `domain/checkout/checkout-request.ts`, `checkout-request.test.ts`。

**Interfaces:** Task 4 CardScanDialog，Task 2 lookup，Task 3 preview/complete。`checkoutFingerprint(visitIds:string[], payments:CheckoutPaymentFingerprint[], memberId:string|null, benefits?:CheckoutBenefits):string` 保持原前三参数兼容；现有 `CheckoutPaymentFingerprint` 中 `amount:number`，实际 HTTP 金额仍沿用现有字符串序列化；第四参包括 pass、排序所选 visit、识别方式、绑定 ID、姓确认。共享新协议类型定义在 `client/src/types.ts`。

- [ ] 扩展指纹失败测试：

```ts
it('changes the checkout identity when pass or binding changes', () => {
  const rows = [{ method: 'cash', amount: 10 }]
  const first = { pass_use: { member_pass_id: 'p1', visit_ids: ['v1'] },
    member_verification: { method: 'card' as const,
      card_binding_id: 'c1', surname_confirmed: true } }
  expect(checkoutFingerprint(['v1'], rows, 'm1', first))
    .not.toBe(checkoutFingerprint(['v1'], rows, 'm1', {
      ...first, member_verification: { ...first.member_verification, card_binding_id: 'c2' } }))
})
```

- [ ] 运行 `npm.cmd exec -- vitest run src/domain/checkout/checkout-request.test.ts src/views/CheckoutView.test.ts`，确认第四参数尚未参与指纹而失败。
- [ ] MemberPaymentSelector 提供手机号/刷卡识别、余额、手动选择哪张次卡、哪些人员抵票、姓核实；默认不选次数。通过 parent emits 返回当前 member/benefits，不自行调用 complete/consume。
- [ ] CheckoutView 根据 server preview 的 amount_due 汇总四种货币付款；不能从前端减字符串凑金额。自动分配只在未人工修改付款时进行；全抵票金额0允许无付款行。
- [ ] 把 member_verification/pass_use 放入原 immutable pending body 和指纹；业务锁包含新读取/预览过程，支付网络结果不明时禁用所有新选择，重试使用原键与原 JSON。
- [ ] 换手机号、取消刷卡、更换会员、visit 选择改变、离页、logout、period change 均清空旧核实及抵次；异步 lookup/preview 使用 generation 丢弃迟到结果，不能覆盖新账单。仅余额付款也重查绑定/姓要求。
- [ ] 增加10元剩余应付、余额不足组合、次卡默认为不使用、两人部分抵票、刷卡 Enter 不付款、无手机号安全显示、迟到查找、未知/撤销卡、超时同体重试测试；保留原混合20现金40支付宝100余额用例。
- [ ] 运行上述测试、PaymentPanel 测试、`npm.cmd run type-check`。提交明确文件，commit：`feat: support card lookup and pass selection at checkout`。

## Task 6：内置历史日志、可滚动窗口及可信发布日期

**Files:** Create `client/src/update/history-data.json`, `release-history.ts`, `release-history.test.ts`, `components/update/ReleaseHistory.vue`, `UpdateCenter.test.ts`。Modify `components/update/UpdateCenter.vue`, `views/LoginView.test.ts`, `stores/runtime.ts`, `env.d.ts`, `electron/updater-controller.cjs`, `updater-controller.node-test.cjs`。

**Interfaces:** `ReleaseHistoryEntry {version:string; publishedAt:string|null; state:'published'|'unverified'|'pending'; source:'user'|'backfilled'; notes:string[]}`；`getReleaseHistory(verified?:{version:string;publishedAt:string}):ReleaseHistoryEntry[]`；`historyDateLabel(entry:ReleaseHistoryEntry):string`。UpdateState 扩展 `releaseVersion:string|null, releasePublishedAt:string|null`，只来自已验签策略。

- [ ] 写历史顺序、原文和未核实时间失败测试：

```ts
import { expect, it } from 'vitest'
import { getReleaseHistory, historyDateLabel } from './release-history'

it('includes all user logs without inventing publish dates', () => {
  const rows = getReleaseHistory()
  expect(rows.map(row => row.version)).toEqual(['0.5.1', '0.5.0', '0.4.9', '0.4.8', '0.4.7'])
  expect(rows[0]!.notes).toEqual(['增加实体卡消费功能'])
  expect(historyDateLabel(rows[0]!)).toBe('待发布')
  expect(rows.find(row => row.version === '0.4.8')!.source).toBe('backfilled')
  expect(rows.find(row => row.version === '0.4.7')!.notes).toContain('“库存管理”界面 UI优化')
})
```

- [ ] 运行 `npm.cmd exec -- vitest run src/update/release-history.test.ts src/components/update/UpdateCenter.test.ts`，确认新数据和组件缺失失败。
- [ ] 录入单一 JSON 源。正式历史原文：
  - 0.4.7：`给前台收银和库管增补“经营报表”权限`、`“经营报表”UI优化`、`“库存管理”界面 UI优化`、`库存预警值设置为商品入库数量的15%`。
  - 0.4.9：`新增 账号注册功能`。
  - 0.5.0：`优化主登录页面`、`新增账号密码修改功能`、`新增搓澡师下单打印小票的功能`、`新增每天小票补打的功能`。
  - 0.5.1：`增加实体卡消费功能`。
  - 0.4.8（补录）：`澡巾、备品、搓泥宝按服务项目下单`、`加单后弹窗选择耗材`、`库存及项目商品每页十项，右上角换页`、`库存成本单价可编辑，首次赋值免密码，后续修改核对本人密码`、`手机版同步更新`。
- [ ] 对确有签名清单/成功发布凭据的版本补 publishedAt，记录证据路径与哈希；找不到则 null/unverified。0.5.1 初始 pending；构建时间/version.json 修改时间不能填历史发布日期。
- [ ] 日期使用 `Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})`；只接受有效 ISO 时间，排序按 semver 数字段。
- [ ] Electron 状态从验签的 desktop policy 提取 releaseVersion/releasePublishedAt，即便决策 none；失败状态不可拿未验签字段覆盖日期。正式发布工具把实际发布时间写签名策略和成功发布记录；发布前安装包内当前版本仍 pending，通过验签策略补充显示时间，不在签名后改安装包字节。无法在线核实时仍诚实显示未知状态，不能把构建时间伪装成已发布。
- [ ] 更新窗口保留当前状态/本次更新和原下载保护，新增 history 组件：

```css
.release-history {
  max-height: min(40vh, 360px);
  overflow-y: auto;
  overscroll-behavior: contain;
}
```

- [ ] 历史区域 `tabindex="0"`、可键盘滚动；渲染使用文本插值/有序列表而非 v-html。footer 位于滚动容器外，窄屏不挤出下载/安装/关闭按钮；更新状态初次加载失败时仍可显示内置日志。
- [ ] 增加未登录、离线、已是最新、长日志、HTML 注入、忙碌安装禁用测试。运行历史/UpdateCenter/LoginView/update-copy Vitest，updater-controller Node tests、type-check；不称旧0.4.x页面已经有新布局。
- [ ] 提交相关文件，commit：`feat: show offline release history in the update center`。

## Task 7：PG17 扩展迁移、保留业务证明与检查点部署

**Files:** Create `deploy/cloud/scripts/desktop_051_guard.py`, `deploy/cloud/scripts/desktop_051_deploy.py`, `scripts/invoke-desktop-051.ps1`, `scripts/tests/test_desktop_051_guard.py`, `test_desktop_051_recovery.py`, `test_desktop_051_entrypoints.py`。Modify `deploy/cloud/docker-compose.prod.yml`。

**Interfaces:** `desktop_051_guard.py` 提供 `snapshot(session) -> dict`, `compare_migration(before:dict, after:dict) -> None`, `prove_runtime_roles(connection) -> dict`；deploy 支持 preflight/deploy/resume，结果包含 job、exact phase、source sha/commit、目标 schema、pinned image 和 origin 证明。completed.json 只能在所有门禁通过后生成。复用现有 operations_backup_verify.py 的实际 PG17 restore，不复用 0.5.0 的删除账号差异白名单。

- [ ] 写 snapshot 差异测试，拒绝任何老会员余额/手机号/员工/库存/审计改动；只容许新增空表和 holder_surname/nullability schema 扩展：

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'deploy/cloud/scripts'), str(ROOT / 'server')]

def test_migration_never_allows_member_balance_drift():
    from desktop_051_guard import compare_migration
    import pytest
    before = {'old_row_hashes': {'members': 'a'}, 'new_row_counts': {},
              'schema_revision': '20261011_service_receipts'}
    after = {'old_row_hashes': {'members': 'b'},
             'new_row_counts': {'member_card_bindings': 0, 'settlement_pass_redemptions': 0},
             'schema_revision': '20261012_physical_membership'}
    with pytest.raises(RuntimeError):
        compare_migration(before, after)
```

- [ ] 项目根运行 `& '.\server\.venv\Scripts\python.exe' -m pytest scripts/tests/test_desktop_051_guard.py -q`，确认新 guard 缺失失败。
- [ ] 快照用老字段投影计算老数据哈希，不因新 surname 字段加入误报；所有旧账户保持，不沿用旧 employee deletion 特例。证据 JSON 私有权限0600，禁止打印 URL/password；公开只输出安全 phase/exit/path。
- [ ] Compose 固化 cleanup256m、stdlib-only 心跳探针：

```python
import json, sys, time
from pathlib import Path
try:
    beat = json.loads(Path('/tmp/xiquan-receipt-cleanup-health.json').read_text())
    healthy = beat['ok'] is True and 0 <= time.time() - beat['checked_at'] <= 120
except Exception:
    healthy = False
sys.exit(0 if healthy else 1)
```

- [ ] 探针通过 CMD/Python -c 使用上述标准库逻辑，interval10s、timeout3s、start_period15s、retries6；不得重复 import app。普通 API 不带维护所有者 URL，merged Compose 只允许经过检查的 worker 内存/健康变更。
- [ ] preflight 上传精准源码并验 hash，核查 schema、healthy API、权限、业务期间、未完成 reset 和磁盘；已有未结账订单保留，不为部署强制删单。使用当前健康 API 镜像离线覆盖源码构建，不从网络再拉依赖。
- [ ] 在隔离 PG17 恢复库执行新迁移并证明：空手机号、唯一卡、有效绑定唯一、append-only/period/屏障、backup可读、runtime最小授权。使用双连接并发验证同一余额/次数不能超扣、补卡与旧卡结算互斥；记录实际 DB 版本/角色/结果。
- [ ] 维护前真实 backup/restore→领取 owned maintenance→精确扩展迁移→after backup/restore→ready→切源码/网页→新 API 暂停 reset worker 启动→只释放本任务维护→恢复 normal worker→cleanup健康。资源门禁每阶段按当前实际预算核查，失败保留 job 不清空。
- [ ] 所有公网/origin验证使用 `curl --http1.1 --output` 写字节后 hash，不用去空白 stdout 比 HTML；验证 API health、四端数据/旧请求兼容、网页资源、cleanup两次心跳与正常 worker。
- [ ] resume 从 exact before/after/ready/maintenance-release/normal-worker/cleanup 证据分类，只补未完成阶段，不重跑迁移、支付、删除账户或用旧API。加入每阶段故障注入测试，原失败命令保留私有原因。
- [ ] PowerShell 支持 `-Mode preflight|deploy|resume -BundlePath -ExpectedSha256 -SourceCommit -Stage -JobDirectory -EcsTarget`；路径/hash/commit严格校验、SSH限时和心跳、必要交互维护确认。用 `powershell.exe -ExecutionPolicy Bypass -File` 调用，不设置永久策略。
- [ ] 运行 guard/recovery/entrypoints 及原共享备份测试；做 merged Compose 定向检查。完成后提交明确文件，commit：`feat: add guarded additive deployment for physical membership`。

## Task 8：四包构建、原信任更新与完整交付指令

**Files:** Create `scripts/lib/desktop-051.cjs`, `scripts/build-desktop-051.ps1`, `sign-desktop-051.ps1`, `desktop-051-publish-entry.ps1`, `scripts/tests/desktop-051.node-test.cjs`, `test_desktop_051_source.py`。Modify `client/package.json`, `client/package-lock.json`。Create `docs/releases/desktop-0.5.1.md` 和交付目录脚本。

**Interfaces:** `desktop-051.cjs` 提供 releaseVersion=`0.5.1`、releaseNotes=`['增加实体卡消费功能']`、四目标、沿用 original public key 的 `signingPlan` 和 candidate/hash检查。交付 metadata 包含 exact commit/源码 hash/四exe hash/真实当前APK路径/hash/本机构建信息；发布入口要求 Task 7 completed 证据与同 commit/schema/image。

- [ ] 写 release 常量及最低版本保留测试：

```js
const test = require('node:test')
const assert = require('node:assert/strict')
test('0.5.1 keeps four supported Windows targets and user notes', () => {
  const release = require('../lib/desktop-051.cjs')
  assert.equal(release.releaseVersion, '0.5.1')
  assert.deepEqual(release.releaseNotes, ['增加实体卡消费功能'])
  assert.deepEqual(release.targets, ['win10-x86','win10-x64','win11-x86','win11-x64'])
})
```

- [ ] 运行 `node --test scripts/tests/desktop-051.node-test.cjs`，确认模块缺失失败。实现基于现有 generic windows/operations 工具，不复制所有旧恢复脚本改版本号。
- [ ] package与lock同时升级0.5.1，不换appid/key/证书。preflight核原公钥和实际 Electron 已验缓存；四目标继续当前可用 runtime（x64 44.5.1、ia32 43.7.7），不为了日志升级依赖。
- [ ] 冻结 committed source；build web/mobile web、四 Windows 包、源码网页ZIP；源码包必须含新模型/API/迁移/UI/history/guard以及完整迁移链。源文件/hash与客户端版本不一致立即停止，不生成假完整交付。
- [ ] 发布前实际获取四策略并验原签名，next sequence > each current；不把连接失败当“首次发布序号1”，保留每目标最低版本/原安装覆盖机制以及旧端需要的兼容更新别名。
- [ ] 交付 `F:\溪泉洗浴系统\最新版安装包-实体卡消费-0.5.1`：四 exe、源码网页zip、SHA256SUMS、交付信息.json、更新日志、`01-部署云端.ps1`、`02-签名并发布桌面更新.ps1`、`03-验证三端与更新.ps1`、`README-完整PowerShell.md`。脚本自己读取同目录 metadata，用户无需粘 stage/hash 手工猜值。
- [ ] 完整指令明确：本机执行、所有 PS5 中文脚本 UTF8-BOM/ASCII安全、每段 exit检查；私钥仅本机签名，密码隐藏；发布需云端completed证明。对当前1.2.9只兼容测试不发布虚假新APK；若任务确需手机兼容补丁则新同签证书构建/应用内更新分支。
- [ ] 并列人工验收表：Win10/11与32/64实机、旧0.5.0和实际保留旧版检查更新→下载→覆盖→保留终端配置、D5扫描、两账户同余额、次卡混合/退款、手机在线同步、服务打印/午夜清理；无法取得实机的一项写“未实测”，不虚报通过。
- [ ] 本机构建验证、包内新模块/公钥/AppID/版本/无私有文件检查、SHA256复核后才能称交付完成。小票/金额保护测试要通过，不因急迫省略财务检查。
- [ ] 提交源码/公开文档（不提交exe到普通代码仓库），commit：`release: prepare desktop 0.5.1 trusted update delivery`。

## Task 9：历史公开文件 GitHub 分类归档与精确清理

**Files:** Create `scripts/archive-desktop-051.ps1`, `scripts/lib/archive-plan-051.cjs`, `scripts/tests/archive-plan-051.node-test.cjs`, `docs/releases/desktop-0.5.1-archive.md`。复用 `scripts/lib/archive-proof.cjs` 的字节证明，扩展明确允许列表而非泛目录删除。

**Interfaces:** `planArchive(root:string, candidates:ArchiveCandidate[]) -> ArchiveEntry[]`，Candidate包括 exact source path/version/platform/type，Entry含 resolved path/size/sha256/remote relative path/split pieces。远端proof需 repo+commit+file字节 hash+时间；只对同一 Entry 叶子文件授权移除。

- [ ] 写超限/私有路径拒绝和 latest 保护失败测试：

```js
const test = require('node:test')
const assert = require('node:assert/strict')
test('private inputs cannot enter the public archive', () => {
  const { planArchive } = require('../lib/archive-plan-051.cjs')
  assert.throws(() => planArchive('F:\\溪泉洗浴系统', [
    { path:'private/溪泉发布密钥/desktop-release-private.pem', version:'0.5.0',
      platform:'desktop', type:'key' } ]))
})
```

- [ ] 运行 `node --test scripts/tests/archive-plan-051.node-test.cjs` 确认失败。实现 resolved exact paths+祖先重解析点拒绝；只接收已枚举旧公开交付，排除当前四包/当前APK/被线上策略引用文件、shared scripts、runtime cache、迁移、.git及必要private。
- [ ] 归档分类 `desktop/<version>/<target>`、`mobile/<version>`、`source/<version>`、`documents/<version>`；>90MiB拆32MiB分片，生成原文件和每片hash/size/顺序/重组操作清单，重组后SHA256必须与源一致。
- [ ] 读 computer-use skill 后打开用户指定 `C:\Users\lenovo\OneDrive\Desktop\GitHub Desktop.lnk`，确认实际仓库是 `https://github.com/Rasmus911/xiquanxiyu`，在 Desktop查看文件、commit并Push。若 native Desktop 无可操作工具，明确交给用户 Push，不能宣称已上传或改CLI偷偷Push。
- [ ] 通过指定repo远端commit读取每个归档实际字节或重组片，核对完整hash；proof24小时以内且路径/hash一致。仅本地commit、文件名相同或待推送状态不是删除依据。
- [ ] 确认最新版三端可重建、旧端更新兼容引用已保留，再 `Remove-Item -LiteralPath <已验证的单个绝对文件>`，非递归；空目录单独确认后移除。记录每个删除文件的远端恢复路径与hash。失败不自动清理任何未证明文件。
- [ ] 执行 archive 测试、dry-run清单并检查 private不出现在公开档案；提交脚本/恢复文档。最终交付说明已归档/保留/未能远端证明的范围，不为了文件夹“看起来干净”删除仍被调用的旧名称脚本。

## 最后一次验收与交接

- [ ] 隔离后端：新card/pass/finance测试 + 当前mixed_checkout、package_orders、会员、权限、reset期间、小票自然日测试；只修本次回归，不扩展其他功能。
- [ ] 前端：新读卡/会员/Checkout/History测试 + type-check/build；Electron updater/receipt测试。
- [ ] 发布工具：051 guard/recovery/source/signing/archive定向测试；真实PG17结果必须来自用户执行的云端脚本，不能拿 mocked unit tests 写成实机证明。
- [ ] `git diff --check`、交付SHA256复核、包内版本/公钥/迁移链确认；保留未触碰用户文件；需要时使用 requesting-code-review 与 verification-before-completion 技能。
- [ ] 向用户给出四个真实安装包路径、源码网页包路径、完整PowerShell文档、待执行云端/签名步骤和实际验收边界。源码完成、安装包完成、云端已部署、远端已归档四种状态分别报告。

## 计划自检记录（2026-10-12）

- Spec 1–3 身份及版本：Task1/2/8；Spec4开户/绑补卡：Task2/4；Spec5–6支付/追责：Task3/5；Spec7兼容迁移：Task1/7/8；Spec8归档：Task8/9；Spec9验收：各task与最后验收；Spec11历史日志：Task6。
- 卡号、绑定引用、次卡选择、核实确认字段前后端同名；Member.phone始终字符串序列化；付款指纹包含所有新增身份/票据选择。
- 次卡抵票不改原消费、不当现金、不单独先核销；退款只返本单实际次数。生日/营销/新手机会员权限/Win7不在本版本范围。
- 阶段恢复必须依真实检查点；普通API不给维护角色凭据；财务/密码/备份保护及原签名不可因赶时间删除。
- 本文件是实施计划，所有未打勾步骤尚未执行；不代表源码、安装包、生产部署或 GitHub 归档已完成。
