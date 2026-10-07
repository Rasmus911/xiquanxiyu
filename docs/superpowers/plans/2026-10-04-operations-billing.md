# 正式目录、套票与手牌迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 正式42项目录、001–100现用手牌、成人/儿童票及不重复计费的套餐，且不丢失历史和库存。

**Architecture:** 稳定目录 reference_code 识别种子与套餐引用；套餐覆盖数量与收费金额分开，消费实物出库不随优惠重算。结构迁移只加字段，目录/编号替换由维护 CLI 在排他锁和已验证备份下执行。

**Tech Stack:** Flask、SQLAlchemy/Alembic、Decimal、PostgreSQL 17、Vue、pytest、Vitest。

**Spec:** [设计第6–8节及资金约束](F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-04-operations-permissions-catalog-upgrade-design.md)

## Global Constraints

继承[总计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-upgrade.md)全部约束，前置 A、B。只允许服务器计算金额/覆盖额度；已结算订单不能重算。默认新品库存0，不动原饮品/余额/流水。套餐A中的“单盐（奶）”只保留内容说明，没有提供的独立价格不得编造。

## 文件责任及契约

- `F:/溪泉洗浴系统/server/app/catalog_defaults.py`：42项不可变正式定义，不执行数据库写入。
- `F:/溪泉洗浴系统/server/app/package_billing.py`：纯包含额度分配，无 Flask/SQL/库存副作用。
- `F:/溪泉洗浴系统/server/app/package_service.py`：套餐应用、撤销、当前订单应收重算与审计，不独立commit。
- `F:/溪泉洗浴系统/server/app/operations_upgrade.py`：预检、验证备份、事务应用、结果核验；使用维护连接，不为公开API提供入口。
- `F:/溪泉洗浴系统/server/app/financial_lock.py`：短金额相关事务的排他串行化锁，先于业务行锁；不是绕过权限或维护屏障。
- `F:/溪泉洗浴系统/server/app/seed.py`：只在空库建立正式默认数据，现有库不隐式替换目录/手牌。

### C1：纯正式目录与稳定项目码

**Files:** 新建 catalog_defaults.py、server/tests/test_formal_catalog.py；暂不改启动种子，防止任务半途自动替换已有库。

**Interfaces:** frozen CatalogSpec(reference_code,kind,category,name,price,mobile_scope,stock_tracked,sort_order,package_slots,display_contents)，`formal_catalog_specs() -> tuple[CatalogSpec,...]`。kind= ticket/service/product/package；package_slots 是每份包含额度的“可选reference_code元组”，不是名称匹配。

固定 reference_code 与金额：

| code | 名称 | kind / scope | 元 |
| --- | --- | --- | ---: |
| ticket.adult | 门票 | ticket/frontdesk | 15 |
| ticket.child | 儿童门票（一米以下） | ticket/frontdesk | 10 |
| bath.scrub | 搓澡 | service/scrub | 10 |
| bath.towel | 澡巾 | product/scrub | 6 |
| bath.supplies | 备品 | product/scrub | 7 |
| bath.mud | 搓泥宝 | product/scrub | 10 |
| bath.wine | 红酒搓 | service/scrub | 10 |
| bath.vinegar | 醋搓 | service/scrub | 10 |
| bath.back | 敲背 | service/scrub | 20 |
| bath.egg | 蛋奶蜜 | service/scrub | 35 |
| bath.gua | 男/女浴刮痧 | service/scrub | 15 |
| bath.roll | 男/女浴擀筋 | service/scrub | 20 |
| bath.cup | 男/女浴拔罐 | service/scrub | 15 |
| bath.combo2 | 二合一 | service/scrub | 15 |
| bath.combo3 | 三合一 | service/scrub | 20 |
| bath.combo5 | 五合一 | service/scrub | 30 |
| bath.combo6 | 六合一 | service/scrub | 40 |
| bath.combo7 | 七合一 | service/scrub | 50 |
| bath.aloe | 芦荟灌肤 | service/scrub | 58 |
| rest.ear | 采耳 | service/rest | 20 |
| rest.cup | 三楼拔罐 | service/rest | 20 |
| rest.leg | 揉腿（20分钟） | service/rest | 30 |
| rest.step | 踩背（20分钟） | service/rest | 30 |
| rest.foot | 精品足疗（20分钟） | service/rest | 30 |
| rest.oilback | 精油开背（30分钟） | service/rest | 98 |
| rest.thai | 泰式按摩（60分钟） | service/rest | 128 |
| rest.oilbody | 全身推油（80分钟） | service/rest | 208 |
| rest.earcandle | 耳烛 | service/rest | 20 |
| rest.roll | 三楼擀筋 | service/rest | 30 |
| rest.abdomen | 腹疗（20分钟） | service/rest | 30 |
| rest.head | 头疗（20分钟） | service/rest | 30 |
| rest.hongkong | 港式按摩（40分钟） | service/rest | 68 |
| rest.classic | 溪泉经典（50分钟） | service/rest | 100 |
| rest.american | 美式按摩（60分钟） | service/rest | 168 |
| rest.supreme | 溪泉至尊（120分钟） | service/rest | 268 |
| package.A | 套票A | package/frontdesk | 45 |
| package.B | 套票B | package/frontdesk | 48 |
| package.C | 套票C | package/frontdesk | 55 |
| package.D | 套票D | package/frontdesk | 78 |
| package.E | 套票E | package/frontdesk | 108 |
| package.F | 套票F | package/frontdesk | 188 |
| package.G | 套票G | package/frontdesk | 218 |

package 的实际 name 为“套票字母（用户所给完整内容）”，短标签和 display_contents 另供界面展示，不省略或改变正式内容。各套餐第一slot均为 (ticket.adult,ticket.child)，只共享一次票额度。其余slot：

```python
PACKAGE_SLOTS = {
 'A': ('bath.scrub','bath.cup','bath.supplies'),
 'B': ('bath.scrub','bath.combo2','bath.cup'),
 'C': ('bath.scrub','bath.combo5','bath.mud'),
 'D': ('bath.scrub','rest.foot','rest.step','bath.supplies'),
 'E': ('bath.scrub','rest.foot','rest.hongkong','bath.supplies'),
 'F': ('bath.scrub','bath.mud','rest.foot','rest.thai','bath.supplies'),
 'G': ('bath.scrub','bath.mud','rest.foot','rest.american','bath.supplies'),
}
```

- [ ] **1. 红测全部定义。** 在 test_formal_catalog.py 保存上述完整42码/名称/价格字典及7组slots；逐项 Decimal 比较，assert reference_code 唯一，3个新品kind=product/tracked，bath/rest权限正确，时长和套餐说明不丢。额外断言没有独立带虚构价格的“单盐/单奶”。

```python
def test_formal_catalog_prices_and_count():
    specs = formal_catalog_specs()
    expected = {
      'ticket.adult':15,'ticket.child':10,'bath.scrub':10,'bath.towel':6,
      'bath.supplies':7,'bath.mud':10,'bath.wine':10,'bath.vinegar':10,
      'bath.back':20,'bath.egg':35,'bath.gua':15,'bath.roll':20,'bath.cup':15,
      'bath.combo2':15,'bath.combo3':20,'bath.combo5':30,'bath.combo6':40,
      'bath.combo7':50,'bath.aloe':58,'rest.ear':20,'rest.cup':20,'rest.leg':30,
      'rest.step':30,'rest.foot':30,'rest.oilback':98,'rest.thai':128,
      'rest.oilbody':208,'rest.earcandle':20,'rest.roll':30,'rest.abdomen':30,
      'rest.head':30,'rest.hongkong':68,'rest.classic':100,'rest.american':168,
      'rest.supreme':268,'package.A':45,'package.B':48,'package.C':55,
      'package.D':78,'package.E':108,'package.F':188,'package.G':218,
    }
    assert len(specs) == len(expected) == 42
    assert {s.reference_code:s.price for s in specs} == {
        code:Decimal(str(price)) for code,price in expected.items()}
```
- [ ] **2. 运行。** `python -m pytest server/tests/test_formal_catalog.py -q`，预期缺 catalog_defaults 模块。
- [ ] **3. 定义实现。** 使用 frozen dataclass 和 Decimal 字符串，全部42条显式内容来自本表及设计套餐表；不从旧数据库名称猜测。ticket不参与快速加单，quick默认正式浴区→按摩→套票→保留商品的相对顺序。

```python
@dataclass(frozen=True)
class CatalogSpec:
    reference_code: str
    kind: str
    category: str
    name: str
    price: Decimal
    mobile_scope: str
    stock_tracked: bool = False
    sort_order: int = 0
    package_slots: tuple[tuple[str, ...], ...] = ()
    display_contents: tuple[str, ...] = ()
```

- [ ] **4. 绿测。** 全42条通过，定义纯函数没有 db/session/current_app 依赖；默认对象不含 stock_quantity=10。历史饮品不属于正式替换集合。
- [ ] **5. 提交。** `feat: define approved operational catalog and package components`。

### C2：手牌与套餐结构迁移，历史不变

**Files:** 修改 server/app/models.py、serializers.py、schema_maintenance.py；新建 server/migrations/versions/20261004_catalog_packages.py、server/tests/test_operations_schema_migration.py。

**Interfaces:** Wristband 增加 bath_area(20) 和 is_active(defaultTrue)；CatalogItem 增加 nullable unique reference_code(80)、nullable package_definition(JSON)；OrderItem 增加 covered_quantity(default0)、package_order_item_id(self FK)、package_snapshot(JSON)。OrderItem 现有 unit_price 是正常毛单价，total_amount 始终是净应收。

- [ ] **1. 红测隔离迁移。** 采用 test_business_period_migration.py 的 tmp_path Config+flask_migrate.upgrade；升到A1revision，写历史男8001/女9001、会员余额、库存、订单和真实审计；保存所有原字段值。升级后只新增字段，原字段逐项相等、审计链有效；旧号码浴区回填male/female，未知号码标other而非猜性别。重复迁移无变化，单一head。

```python
def test_new_fields_exist_after_upgrade(app):
    assert {'bath_area','is_active'} <= set(Wristband.__table__.columns.keys())
    assert {'reference_code','package_definition'} <= set(CatalogItem.__table__.columns.keys())
    assert {'covered_quantity','package_order_item_id','package_snapshot'} <= set(OrderItem.__table__.columns.keys())
```

schema元信息红测只是最小入口；另用tmp_path升级测试在upgrade前后按UUID读取所有旧字段进行相等比较，不用元信息存在冒充历史数据保留。
- [ ] **2. 运行。** `python -m pytest server/tests/test_operations_schema_migration.py -q`。
- [ ] **3. 加字段与守卫。** migration revision=`20261004_catalog_packages`，down_revision=`20261004_employee_entries`。回填旧浴区仅8001–8060、9001–9060；不得在结构migration中停用或改号码/价格/库存。

```python
with op.batch_alter_table('order_items') as batch:
    batch.add_column(sa.Column('covered_quantity', sa.Numeric(12,3), nullable=False, server_default='0'))
    batch.add_column(sa.Column('package_order_item_id', sa.String(36), nullable=True))
    batch.add_column(sa.Column('package_snapshot', sa.JSON(), nullable=True))
    batch.create_foreign_key('fk_order_package_parent', 'order_items', ['package_order_item_id'], ['id'])
    batch.create_check_constraint('covered_quantity_bounds', 'covered_quantity >= 0 AND covered_quantity <= quantity')
```

schema_maintenance 的本地开发兼容分支加相同字段但不替换数据；生产只由 Alembic owner connection迁移。migration完成后在维护owner同一版本安装 database_guards、business_barrier、period_guards，明确新self FK纳入经营期隔离，不能只刷新Python模型。读取 bath_area 优先持久值，旧schema的 dev fallback 只为迁移前兼容；正式升级后业务校验均读字段。serializer 添加 covered_quantity、gross_amount、included_amount、package_order_item_id、package_snapshot，原 total_amount 字段保持净值，不伪造0单价。
- [ ] **4. 绿测守卫。** 原 settled-order trigger保护整个行，因此新增字段同样不可在结算后改；追加直接SQL修改 covered/package_snapshot 的失败测试。install_period_guards 对 self FK检查同经营期，并新增同 visit、父kind=package约束测试，不能覆盖另一个人的套餐。跑历史迁移/财务完整性/审计回归。
- [ ] **5. 提交。** `feat: add persistent bath areas and auditable package billing fields`。

### C3：带备份、排他锁和预览摘要的数据替换 CLI

**Files:** 新建 server/app/operations_upgrade.py、operations_backup.py、server/tests/test_operations_upgrade.py、test_operations_upgrade_pg.py、test_operations_backup_receipt.py；修改 app/__init__.py（注册CLI）、business_barrier.py、seed.py、deploy/cloud/docker-compose.prod.yml（只增加maintenance的只读备份配置/私有volume）、deploy/cloud/scripts/runtime-role.sql（核对权限不扩权）。C3定义和红/绿测试私有receipt验证器；R3扩展备份/真实恢复执行，不反向依赖尚未完成的部署脚本。

**Interfaces:**

```text
flask operations-upgrade preview --output <private-json>
flask operations-upgrade apply --preview-sha256 <sha> --backup-receipt <private-json> --confirm operations-20261004
flask operations-upgrade verify
```

`preview_upgrade(session)->dict` 输出版本、当前修订/经营期、候选旧服务ID、保留商品ID/库存、旧/新编号、冲突及阻塞手牌，不含密码/DSN。`apply_upgrade(connection,preview_sha,backup_receipt)->dict` 内部只接受已验证维护连接；成功设置 SystemSetting key=operations_upgrade_20261004，记录digest/时间，不保存私人备份路径到公开API。

内部具体接口均在 operations_upgrade.py 定义，避免执行者各自猜名字：

- `maintenance_connection() -> ContextManager[Connection]`：只给显式CLI使用，基于该maintenance进程已有db.engine建立连接，验证实际owner身份，非HTTP入口。
- `verify_preview_and_backup(connection:Connection,preview_sha:str,backup_receipt:Path) -> dict`：返回经digest核对的preview，调用本任务operations_backup.validate_backup_receipt；验证后结束只读事务，不能让下一个connection.begin嵌套autobegin。
- `mark_maintenance(connection:Connection,task_id:str) -> None`：更新单行business_state的维护字段；不自行commit。
- `apply_formal_catalog(session:Session) -> dict[str,CatalogItem]`：按稳定码返回正式项目映射并设置package ID slots，保留商品库存；不commit。
- `retire_legacy_wristbands_and_create_hundred(session:Session) -> dict`：返回retired_ids/new_ids，不commit。
- `record_upgrade_audit(session:Session,preview:dict) -> None`：调用write_audit指定session记录清单前后与digest；不commit。
- `clear_maintenance_in_same_success_transaction(session:Session) -> None`：只清本次维护标记，不改经营期/策略，不commit。
- `validate_backup_receipt(connection:Connection,receipt_path:Path,expected_revision:str) -> dict` 位于operations_backup.py，错误类型 `BackupReceiptError(ValueError)`。receipt固定schema=1、dump_sha256/size/db_name/alembic_revision/business_period_id/business_revision/audit_checkpoint，restore={status:'verified',pg_major:17,checked_at,checks_sha256}；校验私有路径/文件权限、实际dump哈希以及当前数据库快照，拒绝list-only、旧revision、缺恢复证据和可公开写receipt。单元只用fixture，真正verified receipt由R3恢复阶段产生。

- [ ] **1. 红测拒绝和幂等。** 文件SQLite tmp_path fixture建旧120手牌、历史结算和商品实际库存5。open/settling/未解决lost/重置queued或running/目标编号冲突/多个澡巾候选/预览过期/错误备份receipt分别拒绝，所有业务原值不变。正常转换恰100有效号码，旧行/历史票仍8001/9001，余额与原商品库存5不变，新备品/搓泥宝0；重启seed和二次apply不恢复旧数据、重复stock或把新库存改回0。

```python
def test_open_visit_blocks_preview_application(app):
    band = Wristband.query.filter_by(number='8001').one()
    band.status = 'in_use'
    db.session.add(Visit(wristband_id=band.id, status='open'))
    db.session.commit()
    preview = preview_upgrade(db.session)
    assert preview['can_apply'] is False
    assert band.id in preview['blocking_wristband_ids']
    assert Wristband.query.filter_by(number='001').count() == 0
```

该fixture在C4旧种子调整后明确建立legacy120；不得依赖默认种子继续制造8001。
- [ ] **2. 运行。** `python -m pytest server/tests/test_operations_upgrade.py -q`，阻塞用例不得通过自动关闭订单来“解决”。
- [ ] **3. 实现连接和事务步骤。** 使用现有maintenance compose service的 `DATABASE_URL=${MAINTENANCE_DATABASE_URL}`；维护CLI基于该进程db.engine校验目标db_name与私有receipt一致、实际session_user是owner，配置不输出。**不让普通API进程读取owner DSN，不增加其访问owner密码的能力。** 沿用固定排他barrier key713829417，限定同一物理connection，真正获取exclusive后才设置maintenance/maintenance_reset_id。普通shared_barrier和控制表保护仍存在。

业务 SQL barrier 新增明确的维护owner分支：实际session_user是受保护业务表的真正owner **且** 同连接持有该固定ExclusiveLock才可在维护窗口写目录/手牌；若public schema以pg_database_owner伪角色拥有，解析实际database.datdba而非宽泛role membership。不能通过current_user/SET ROLE/GUC/header伪造；xiquan_app和xiquan_backup即使自己抢到advisory锁也不得绕过maintenance。保留xiquan_reset原最小grant，不给它INSERT目录/任意UPDATE价格。

```python
with maintenance_connection() as connection:
    with exclusive_barrier(connection, 'operations-20261004'):
        preview = verify_preview_and_backup(connection, preview_sha, backup_receipt)
        connection.rollback()  # 结束只读autobegin，仍持有session级exclusive lock
        with connection.begin():
            mark_maintenance(connection, 'operations-20261004')
        with Session(bind=connection) as session:
            apply_formal_catalog(session)
            retire_legacy_wristbands_and_create_hundred(session)
            touch_catalog_layout(session)
            record_upgrade_audit(session, preview)
            clear_maintenance_in_same_success_transaction(session)
            session.commit()
```

这些内部函数职责逐项对应：校验备份哈希/schema/审计checkpoint及恢复receipt；比对预览当前修订；maintenance只改现状态字段不改period/policy；按reference_code创建正式定义并将slots转为目录ID；旧service/ticket/package停用；唯一旧澡巾复用ID，所有其他商品保留；旧有效行退役，新号码按正确浴区建立；write_audit(session=session)写同事务证据。失败rollback保留maintenance供人工核对，不能异常finally中盲目解除；不重新创建connection后继续apply。maintenance进程关闭reset worker/socket poll/SMS，不与正常API后台竞争。

seed 规则：空目录/空手牌才建立正式定义与100号码；已存在资料只确保非破坏性settings，任何替换交给CLI。首次空库defaults也为新品0，existing drinks不补回旧耗材。目标同名/同码已有异常不覆盖。snapshot的净amount不在此次迁移重算，因为任何open账单都应预检阻止。
- [ ] **4. 绿测和 PG 权限。** 本地一次性PG17验证owner+exclusive可写；app+伪造GUC/SET ROLE/exclusive锁仍被维护屏障拒绝；backup角色仍只读，reset角色不能改价/INSERT手牌。并发runtime加单和维护apply只有完整的先/后结果，没有半新目录。备份恢复由R3实际验证，未有PG运行环境明确记录验证缺口，不能发布。
- [ ] **5. 提交。** `feat: add previewed recoverable operational catalog and wristband cutover`。

### C4：每张手牌的成人/儿童票

**Files:** 修改 server/app/api/wristbands.py、visits.py、serializers.py、client/src/views/DashboardView.vue、VisitView.vue、types.ts；新增 server/tests/test_ticket_selection.py、client/src/domain/wristbands/tickets.ts / .test.ts。

**Interfaces:** open body `ticket_catalog_item_id?:str`（缺省adult）；link-batch body `ticket_catalog_item_ids?:{wristband_uuid:ticket_uuid}`，仅空闲将开牌者需票种，已有活动visit不覆盖。PATCH `/api/visits/<uuid>/ticket` body `{ticket_catalog_item_id,version,idempotency_key}`，需要visit:write，锁当前visit，套票存在时重算覆盖。

- [ ] **1. 红测。** owner开001默认15、开051儿童10、联动混合逐张票种正确；伪造服务/product ID当票种拒绝，不开牌；员工/库管直接改票拒绝；结算后改票拒绝。linked existing visit既有票种不被批量map改写，retired旧ID open/switch/recover拒绝。

```python
def test_explicit_child_ticket_is_ten(client, strict_owner_session):
    band = Wristband.query.filter_by(number='051', is_active=True).one()
    ticket = CatalogItem.query.filter_by(reference_code='ticket.child').one()
    response = client.post(f'/api/wristbands/{band.id}/open',
        headers=strict_owner_session['headers'], json={'ticket_catalog_item_id':ticket.id})
    assert response.status_code == 201
    visit = Visit.query.filter_by(wristband_id=band.id, status='open').one()
    total = sum((x.total_amount for x in OrderItem.query.filter_by(visit_id=visit.id,status='active')), Decimal(0))
    assert total == Decimal('10.00')
```

此用例依赖formal_catalog fixture；fixture明确在隔离库应用正式定义和100牌，不调用维护云端CLI。
- [ ] **2. 运行。** `python -m pytest server/tests/test_ticket_selection.py -q`；client `npx.cmd vitest run src/domain/wristbands/tickets.test.ts`。
- [ ] **3. 实现。** `_active_ticket` 改可接受指定ID并默认 reference_code=ticket.adult；`_create_visit` 和 link空闲分支显式传ticketID。可售票种GET在授权营业读数据返回，不让普通员工能写。ticket PATCH 同时保留旧行记录/审计（原票行voided、新票行active），不物理删票；C6接入时调用重算器。dashboard开牌确认里逐人radio成人/儿童，表单金额只展示server单价，不发money。

```python
ticket = CatalogItem.query.filter_by(id=ticket_id, kind='ticket', is_active=True).first()
if not ticket or ticket.reference_code not in {'ticket.adult','ticket.child'}:
    raise ApiError('请选择有效成人或儿童门票', 400, 'INVALID_TICKET')
```

- [ ] **4. 绿测及旧流程迁移。** main_flow先保留 legacy fixtures明确生成旧手牌/0票测试，新增正式fixture使用新100编号/15票。不要仅把expected金额改大而漏测恢复挂失20、单独结账、换牌、联动独立票种。A3服务范围改读取bath_area，测试新001/051边界；所有当前手牌查找规范化三位字符串、历史查询不规范化旧值。
- [ ] **5. 提交。** `feat: support per wristband adult and child admission selection`。

### C5：纯覆盖分配器和金额写锁

**Files:** 新建 package_billing.py、server/tests/test_package_billing.py；扩展B3创建的financial_lock.py、server/tests/test_financial_lock.py；修改金额写端的授权装饰器顺序（visits/checkout/inventory/members/wristbands/catalog/settings）。

**Interfaces:** frozen BillingLine(id:str,catalog_item_id:str,quantity:Decimal,unit_price:Decimal,order_index:int)；PackageSlot(catalog_item_ids:tuple[str,...],quantity:Decimal)；`allocate_inclusions(lines:list[BillingLine],slots:list[PackageSlot])->dict[str,Decimal]`；`line_net_total(line:BillingLine,covered:Decimal)->Decimal`；复用B3 `serialized_financial_write` 装饰器，在身份权限验证后、行锁前拿PG transaction advisory key713829418，在commit/rollback释放，SQLite隔离测试验证调用顺序。

- [ ] **1. 红测计算表。**

```python
def test_package_a_net_with_water():
    lines = [BillingLine('t','adult',Decimal(1),Decimal(15),0),
             BillingLine('s','scrub',Decimal(1),Decimal(10),1),
             BillingLine('c','cup',Decimal(1),Decimal(15),2),
             BillingLine('w','water',Decimal(1),Decimal(3),3)]
    slots = [PackageSlot(('adult','child'),Decimal(1)),
             PackageSlot(('scrub',),Decimal(1)),PackageSlot(('cup',),Decimal(1))]
    covered = allocate_inclusions(lines, slots)
    total = Decimal(45) + sum(line_net_total(x,covered[x.id]) for x in lines)
    assert total == Decimal('48.00')
```

参数化：重复cup2只覆盖1、备品3覆盖1、child票替代adult共用一次、匹配多行只覆盖最早、slot清空恢复全额、金额非负且两位小数、非法quantity/covered拒绝。锁测试记录 order 权限→financial-lock→row-lock→audit，403请求不得进financial-lock。
- [ ] **2. 运行。** `python -m pytest server/tests/test_package_billing.py server/tests/test_financial_lock.py -q`。
- [ ] **3. 实现纯计算。** 按order_index稳定排序；每slot以Decimal剩余额度消费匹配行未覆盖quantity；slot之间不得重复定义同一目录ID；lines必须唯一ID、正quantity/非负价格。净额定义：

```python
def line_net_total(line, covered):
    if not Decimal('0') <= covered <= line.quantity:
        raise ValueError('included quantity out of bounds')
    return (line.unit_price * (line.quantity-covered)).quantize(Decimal('0.01'))
```

金额写串行锁用于当前单店单API节点，减少调价/结账/加单的互锁竞争；保留所有对象行锁、period/barrier/权限检查，不把advisory当身份授权。各处理器 commit前不得做慢网络短信/打印；既有外部发送留在commit后。重价、票种、package的直接service调用同样受该锁保障。test PG两个不同幂等key并发竞争账单仍只有合法先后，不重复覆盖或出库。
- [ ] **4. 绿测。** 纯引擎不访问db/current_app，所有边界和锁顺序通过；回归原checkout/member/inventory幂等测试，不能因串行化改付款口径。
- [ ] **5. 提交。** `feat: add deterministic package inclusion allocation and ordered money writes`。

### C6：套餐 API、加单集成和前端展示

**Files:** 新建 package_service.py、server/tests/test_package_orders.py；修改 visits.py、mobile.py、catalog.py、pricing_service.py、auth_service.py、access_policy.py、employee_access.py；修改双前端types/selection/filter/CatalogPicker与VisitView、VisitOrderView；增加双端 package-selection.test.ts。

**Interfaces:** `recompute_visit_billing(session,visit)->dict`（变更前后净额/coverage，不commit）；`set_visit_package(session,visit,catalog,employee)->OrderItem`；`cancel_visit_package(session,visit,employee)->None`。POST `/visits/<id>/package` body `{catalog_item_id,version,idempotency_key,confirm_replace}`；DELETE同路径用于取消（body version/idempotency_key）；mobile对应 `/mobile/visits/<id>/package`，保留手机入口scope。普通batch可携带最多一条kind package，服务端先应用package再普通项目，最终只一次重算/commit。

- [ ] **1. 红测真实流程。** formal fixture直接调用仅用于TestConfig的 `apply_formal_catalog(session)` / `retire_legacy_wristbands_and_create_hundred(session)`，只作用隔离库，真实owner HTTP开001并加搓澡/拔罐后setA=45，addwater=48；add额外cup=63。加入备品3覆盖1、库存扣3；setA之前已卖备品不二次出库。换B、取消、重试同key、更改同key payload、已settled、未知packageID、跨角色和另一visit的parent覆盖逐项验证无半写。

```python
def test_client_cannot_set_package_amount(client, strict_owner_session):
    package = CatalogItem.query.filter_by(reference_code='package.A').one()
    band = Wristband.query.filter_by(number='001', is_active=True).one()
    client.post(f'/api/wristbands/{band.id}/open', headers=strict_owner_session['headers'], json={})
    visit = Visit.query.filter_by(wristband_id=band.id,status='open').one()
    response = client.post(f'/api/visits/{visit.id}/package', headers=strict_owner_session['headers'],
        json={'catalog_item_id':package.id,'version':visit.version,'idempotency_key':'fixture-package-a',
              'total_amount':'0.01'})
    assert response.status_code == 400
    assert OrderItem.query.filter_by(visit_id=visit.id,kind='package').count() == 0
```

两个联动手牌分别A/B，selected checkout只结一个且另一个额度不变。mobile最高管理员可选包，普通服务员工只能添加其授权的实际包含项目，不可选/换包；点一次包含service应收0，不回传由客户端指定0price。没实际点的套餐说明项目不凭空创建order/stock movement。
- [ ] **2. 运行。** `python -m pytest server/tests/test_package_orders.py -q`；双端 `npx.cmd vitest run src/domain/orders/package-selection.test.ts`（mobile在src/order-package.test.ts）。
- [ ] **3. 实现服务与事务。** 锁open visit、active lines/目录，最多一个active package。父package qty1，package_snapshot复制code/schema/display/ID slots；已有父不同则要求confirm_replace并审计旧父void、新父生效。引擎给每条实点行covered_quantity/ref，total_amount=净应收，unit_price不改0；部分包含商品显示“包含1件、另2件收费”。取消父先清覆盖恢复现有实际订单净额，不调整已销售实物库存。normalvoid商品只返一次quantity，随后重算其余包含额度。

```python
coverage = allocate_inclusions(lines, slots)
for item in active_non_package_items:
    item.covered_quantity = coverage[item.id]
    item.package_order_item_id = package.id if item.covered_quantity else None
    item.total_amount = line_net_total(by_id[item.id], item.covered_quantity)
```

package:write角色仅cashier/manager/绑定admin；mobile最高scope显式package:write，staff不授。body不接受unit_price/total_amount/covered_quantity等用户金额。C2净serializer和package_snapshot只由服务端设置。价格/定义更新：在同事务锁相关open visits，更新gross/definition，重算净，settled不碰；列出before/after写审计。定义校验ID存在、非package/compensation、无重复slot，含一个票slot。

UI package卡片qty1、另选包清之前包选择；提交捕获包ID及confirm状态纳入B1快照/幂等指纹，变更提示价格来自服务器。复用顶部submit和全局layout；service筛选包含package，普通员工因数据范围不会见收费套票。取消用明确“取消套票，现有项目恢复单项收费”提示；客户端合计预览不是结账权威。
- [ ] **4. 绿测。** 通过套餐/库存/切换快照/金额重价/权限回归，检查ticket change仍重算package覆盖。API返回后更新所有联动引用的金额，但不改其他手牌package。audit chain和financial integrity为true。
- [ ] **5. 提交。** `feat: integrate audited non duplicating packages across ordering clients`。

### C7：小票、经营报表和金额完整性回归

**Files:** 修改 server/app/financial_integrity.py、api/checkout.py、api/reports.py、serializers.py、client/electron/main.cjs（仅必要小票模板字段）、client/src/views/PrintJobsView.vue、ReportsView.vue、mobile/src/views/ReportsView.vue；新增 server/tests/test_package_financial_outputs.py、client/electron/package-receipt.node-test.cjs。

**Interfaces:** receipt line沿用unit_price/quantity/total_amount并增加covered_quantity/included_amount；展示毛单价不等于再次加收入，实际行subtotal是total_amount。报表新的kind=package中文“套票”；主经营收入从Settlement净额，商品/项目分类金额从净应收，同一包仅入账一次。

- [ ] **1. 红测结算/打印/报表。** A+water现金48，receipt明细gross/包含/净相符；小票“套票内”标注能区分，合计48。items report package=45/water=3/包含项目=0，summary/trend收入48。stored balance付款48只减余额48，充值仍独立现金流不重记。**现有次卡核销在独立members/consume API，而非checkout扣款接口**：本次不发明次卡抵套票机制；套票操作与结账不自动扣次数，保留已有次卡开卡/核销流水与幂等回归。补打只增attempt，不产生支付或重复收入。

```python
def test_total_formula_accounts_for_included_quantity():
    line = BillingLine('supplies','supplies',Decimal(3),Decimal(7),0)
    assert line_net_total(line,Decimal(1)) == Decimal('14.00')
```

此外用真实checkout现金/balance各结一次隔离visit，读取receipt和reports API而非仅调用纯引擎；financial_integrity新增负例用未结算订单非法coverage/parent/net值，确保报错并定位订单ID。
- [ ] **2. 运行。** `python -m pytest server/tests/test_package_financial_outputs.py -q`；client `node --test electron/package-receipt.node-test.cjs`。原financial_integrity主要核对ledger/结算/净订单合计；红测针对其尚缺覆盖合法性及逐行净额公式校验，不能误称已有gross*qty检查。
- [ ] **3. 接入统一净额。** financial_integrity校验total=round(unit_price*(qty-covered),2)，并校验covered/ref/parent同visit、同period、唯一activepackage、coverage不超slots。checkout.preview/complete全部使用server net aggregate；不信客户端payment金额，既有差额检验/幂等不移除。打印模板使用receipt.total_amount及每行total_amount，package parent显示总价、children标包含数量；不重新以gross单价相乘覆盖净值。报表分类支持package，不更改现金/储值/次卡防重复统计口径。

```python
violations = []
for item in active_items:
    expected = (Decimal(item.unit_price) *
        (Decimal(item.quantity)-Decimal(item.covered_quantity))).quantize(Decimal('0.01'))
    if Decimal(item.total_amount) != expected:
        violations.append({'code':'ORDER_NET_MISMATCH','order_item_id':item.id})
```

`active_items`从原完整性检查session授权查询取得；把violations纳入原report错误集合，不替换ledger/settlement核对。该公式之外仍须逐slot验证parent合法性，不能只让自洽但伪造包含额度的订单通过。
- [ ] **4. 绿测及全回归。** pytest server/tests 全量、双前端type-check/test/build、Electron打印/IPC/更新安全、PG触发器和并发。历史结算后PATCHcatalog仍不能改原票金额/套餐定义快照；直接SQL改settled任意新增字段都拒绝。遗留测试中旧0门票、120号码用显式legacyfixture，正式新测试的15/10门票覆盖新流程。
- [ ] **5. 提交。** `fix: reconcile package receipts reports and financial evidence`，记录设计验收9–14、所有数据保留断言后进入R2。
