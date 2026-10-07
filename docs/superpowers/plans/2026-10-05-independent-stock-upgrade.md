# Independent Stock Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver independent unit-converting stock, manual ordering consumption, unified cashier/inventory permissions, six desktop installers and Android updates without destroying existing business evidence.

**Architecture:** Keep sales CatalogItem separate from a new StockItem master. Store new stock movements and immutable per-order consumption with conversion snapshots, all through the existing financial write, business period, session and audit protections. UI clients consume the exact REST contract below; packaging uses existing target-specific trusted update machinery.

**Tech Stack:** Flask, SQLAlchemy/Alembic, PostgreSQL 17, Vue 3/Element Plus, Capacitor Android, Electron/NSIS, PowerShell 5.

**Spec:** F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-05-independent-stock-upgrade-design.md (user approved 2026-10-05).

## Global Constraints

- 不清空会员、余额、历史订单、员工、库存流水或审计链，不删除 ECS 文件。
- 两张照片上的数量已由用户确认为实际剩余库存，而不是历史采购数量。
- 4 箱、每箱 200 袋，应形成 800 袋现存数量。入库可选择箱，实际耗用以袋等最小消耗单位扣减。
- 收银员和库管具有相同的五项业务模块权限：手牌、会员、小票补打、项目服务、库存管理。不得因此获得管理员、报表、审计、员工管理、退款或数据库重置权限。
- 手机的会员收银及 USB 小票打印不在本次新建；仍由桌面完成。
- 照片第 22—24 行只处理一次；看不清的名称、单位或数量不猜填入账。
- Win7 只按现有 SP1/Electron 22.3.27 目标制包，不宣称旧运行时安全或未经验证的实机适配。
- win11-x86 是在 Win11 64 位系统运行的 32 位应用。
- 原桌面更新公钥、原 Android 包名/签名证书不更换；密码只由用户本地隐藏输入。
- 云端部署由用户执行完整 PowerShell；本次代理不 SSH、不发布、不删除云端文件。
- 不触碰现有无关未提交文件；每任务只提交自己明确拥有的文件。

## Shared REST contract

All responses retain existing `{success,data,message,request_id}` envelopes. Decimal quantities and prices are serialized as strings.

`StockItem` JSON:

```json
{"id":"uuid","name":"奶浴袋","category":"搓澡耗材","base_unit":"袋","package_unit":"箱","units_per_package":"200.000","package_spec":"1*200","stock_quantity":"800.000","low_stock_threshold":"20.000","is_active":true,"version":1,"legacy_catalog_item_id":null}
```

Endpoints:

- `GET /api/inventory/stock-items`: inventory:read, active-only by default, `include_inactive=true` available for management.
- `POST /api/inventory/stock-items`: inventory:write; name, category, base_unit, package_unit, units_per_package, package_spec, opening_quantity, opening_unit (`base` or `package`), low_stock_threshold. Required Idempotency-Key.
- `PATCH /api/inventory/stock-items/<id>`: inventory:write; optimistic version, name/category/packaging/threshold. Basic unit cannot change after movements. Required Idempotency-Key.
- `DELETE /api/inventory/stock-items/<id>`: inventory:write; JSON version and confirm_writeoff boolean. Nonzero requires confirm_writeoff=true; writes audited loss then archives. Required Idempotency-Key.
- `POST /api/inventory/stock-adjust`: inventory:write; stock_item_id, version, movement_type (purchase/return/loss/adjust/opening), quantity, input_unit (`base`/`package`), reason; returns master and movement. Required Idempotency-Key. `adjust` is signed delta, not a target balance.
- `GET /api/inventory/stock-movements`: inventory:read; optional stock_item_id.
- `GET /api/inventory/consumables`: visit:order/mobile:order; active stock id/name/category/base_unit/package_spec/stock_quantity/version only; no buying cost or write authority.
- `GET /api/inventory/usage`: inventory:read or catalog:read; list of catalog_item_id, catalog_name, stock_item_id, stock_name, base_unit, usage_count, total_quantity, is_most_used (ties preserved). Valid nonvoid order lines only.
- Existing GET /inventory, /inventory/movements, POST /inventory/adjust preserve compatibility; do not break old clients.

New order line payload for existing desktop and mobile single/batch ordering routes:

```json
{"catalog_item_id":"service-uuid","quantity":"1","inventory_mode":"manual","inventory_consumption":[{"stock_item_id":"stock-uuid","quantity":"1"}]}
```

An empty list with mode manual explicitly means no consumption. Missing both fields is legacy behavior. Duplicate stock IDs, malformed mode, missing list, nonpositive/nonfinite/overprecision quantities are rejected. Per-line quantities are totals; do not multiply them by order quantity or packaging factor. Visit detail order rows expose `inventory_consumption` with stock_item_id/name/base_unit/quantity snapshots.

## Task 1: Server permissions, stock ledger and transactional consumption

**Files:**
- Modify server/app/models.py, auth_service.py, employee_access.py, ordering_scope.py, serializers.py, api/inventory.py, api/catalog.py, api/visits.py, mobile ordering service/router, period/reset helpers and relevant PostgreSQL role SQL.
- Create server/app/stock_service.py and server/migrations/versions/20261005_independent_stock.py.
- Create server/tests/test_independent_stock.py; extend relevant role/channel/order regressions.

**Interfaces:** Produces the shared REST contract above. Migration creates independent stock masters for legacy tracked products without rewriting historical inventory movements; old API writers and new writers use one authoritative balance for migrated products. Ordering and rollback remain atomic under financial-write serialization. Add stock table permissions to runtime and maintenance/reset/backup role machinery, and stock period reset cleanup in FK-safe order.

- [ ] Write failing integration tests using admin_session and new API routes. Assert literals, not helper-computed expectations:

```python
def test_case_opening_becomes_basic_units(client, admin_session):
    r = client.post('/api/inventory/stock-items', headers={**admin_session['headers'], 'Idempotency-Key':'stock-open-test'}, json={'name':'奶浴袋','base_unit':'袋','package_unit':'箱','units_per_package':'200','opening_quantity':'4','opening_unit':'package'})
    assert r.status_code == 201
    assert r.get_json()['data']['stock_quantity'] == '800.000'
```

- [ ] Run `server/.venv/Scripts/python.exe -m pytest server/tests/test_independent_stock.py -q` from repo with the server test path configuration used by existing suite; observe missing route/behavior failures, not fixture import failures.
- [ ] Implement StockItem, StockMovement, OrderStockConsumption plus focused stock_service conversion, locking, migration mapping and rollback. Validation uses Decimal with an explicit three-decimal quantity contract:

```python
value = Decimal(str(raw))
if not value.is_finite() or value <= 0 or value != value.quantize(Decimal('0.001')):
    raise ApiError('库存数量必须为大于零、最多三位小数的数字')
```

- [ ] Add permissions to both roles, remove inventory catalog product-only restriction, allow catalog module based on permission rather than manager/admin role name, expand full_ordering correctly. Preserve strict UUID administrator policy and channel barriers.
- [ ] Integrate manual selection in BOTH desktop single/batch and mobile single/batch ordering. Lock all affected stock rows in deterministic order; reject insufficient aggregate availability across batch before partial commit. Legacy goods use migrated master balance and old movement semantics; manual requests never double-deduct.
- [ ] Void returns exact recorded consumption once, including archived master; active usage query excludes voided lines and handles ties.
- [ ] Add behavioral tests for purchase conversion, change-factor snapshots, archival writeoff, manual empty selection, duplicate replay, inadequate batch rollback, legacy coexistence, void twice, basic unit mutation, role permissions, usage ties and sensitive API denial.
- [ ] Run full server pytest; run migration upgrade on an isolated local DB only and validate PostgreSQL privilege/reset migration changes through the available integration harness. Report any unavailable actual PostgreSQL evidence honestly.
- [ ] Self-review and commit only owned server/role SQL/test files; report commands and red/green outcomes.

## Task 2: Desktop and web workflow

**Files:** client/src/types.ts, views/InventoryView.vue, views/CatalogView.vue, views/VisitView.vue, related quick order/picker components, router/stores only as required; create focused inventory and order UI tests/utilities.

**Interfaces:** Consumes Task 1 exact endpoints. Uses shared StockItem fields and per-line manual order payload; adds no competing stock ledger. Reuses pending-idempotency and period/generation guards.

- [ ] Write failing user-facing tests for conversion preview and order consumption payload. A pure focused utility can support actual UI with literal expectations:

```ts
expect(previewStockQuantity('4','package','200')).toBe('800.000')
expect(buildManualConsumption([{stock_item_id:'s1',quantity:'1'}])).toEqual({inventory_mode:'manual',inventory_consumption:[{stock_item_id:'s1',quantity:'1'}]})
```

- [ ] Run relevant Vitest tests red.
- [ ] Add inventory independent new/edit/archive dialogs, base/packaging unit input, conversion preview, receiving input unit selector, movement history and per-catalog most-used stock view. Use per-unit summaries; do not sum bags and bottles as a meaningless total.
- [ ] Hide inactive catalog by default, permit all service/product name/price edits through server-provided capabilities, preserve existing open-price refresh and settled snapshots. Expose protected admin inactive filter.
- [ ] Add per-selected-order-line manual consumption editor with multiple stock rows and explicit no-consumption state, show basic unit and availability, reset when order/visit changes, retain stable selection while choosing linked wristbands. Keep final add-order button in the existing top-right location.
- [ ] Use exact new payload for single and quick batch APIs; retries preserve keys, stock.changed/inventory.changed subscriptions refresh views, server errors remain actionable.
- [ ] Run client tests and npm.cmd run build; self-review, commit only client source/test files. Do not bump/sign/publish release during this task.

## Task 3: Android and mobile web workflow

**Files:** mobile/src/views/InventoryView.vue, VisitOrderView.vue, mobile catalog components, types/capability/router/profile files, plus focused stock/conversion UI tests; create CatalogView.vue if not present.

**Interfaces:** Same REST and payload as desktop. Inventory/cashier/admin capabilities expose stock and catalog editing only when allowed. Scrub/rest staff only see active wristbands and allowed sales; they use consumables endpoint without inventory-write authority.

- [ ] Write failing tests for package input conversion, staff manual stock payload and unauthorized catalog/stock route access.
- [ ] Run mobile tests red.
- [ ] Implement mobile stock CRUD/receiving with packaging preview and independent inventory; catalog name/price edit for permitted roles; service/product ordering with per-line stock consumption, explicit no-consumption and retry identity preservation.
- [ ] Keep three protected administrators’ login channels and highest capabilities compatible; preserve APK download no-device-gate behavior and original package/cert metadata. Do not add mobile financial checkout or USB printing.
- [ ] Run `npm.cmd test`, `npm.cmd run type-check`, `npm.cmd run build`, native:sync (no signing/password use), and APK web asset checks when an unsigned build is available.
- [ ] Self-review and commit only mobile task-owned source/test files; leave unrelated mobile/version.json existing user edit until explicit version bump task.

## Task 4: Photo inventory import and trusted multi-target release pipeline

**Execution subdivision (2026-10-05):** Implement and review sequentially as 4A protected photo import/API/CLI, 4B trusted local six-target build/source/sign/publication preparation, and 4C human-run additive PG17 cloud driver/transport/instructions. Scope and acceptance below are unchanged. Separate harnesses and migration/security judgment make one implementer context too broad; no parallel implementation or implicit cloud execution.

**Files:** create docs/inventory/2026-10-05-photo-stock-review.csv, scripts/build-stock-upgrade.ps1, scripts/deploy-stock-upgrade.ps1, scripts/stock_import.py or API import/CLI backed by Task 1 service, release manifest helper and its tests; modify target publishing helpers only where required; create readable PowerShell instructions.

**Interfaces:** Imports a reviewed CSV with source_photo,row,name,category,base_unit,package_unit,units_per_package,package_quantity,basic_quantity,review_status. Import preview is nonmutating; apply requires a user-confirmed reviewed data file and records a source-hash identity. Final stock equals converted photo remaining stock, not sum with prior balances. Unknown photo fields remain unresolved and block only those rows, explicitly excluded from applied summary.

- [ ] Read both original images and transcribe distinct rows 1–43; preserve evidence/ambiguities. This is a human-data artifact, not invented test content. Packaging 1*200 must distinguish the actual basic unit; never default every item to bags.
- [ ] Write failing tests using a literal 4-box/200-bag CSV and repeat-apply fixture, assert preview=800.000, apply target=800.000 and repeated apply causes no added movement. Test invalid/unknown units, duplicate overlapping source rows, and source-hash verification.
- [ ] Implement safe import and user-readable preview/apply commands using the stock service/audit protections; do not execute against cloud.
- [ ] Write failing release-manifest tests for six target entries, original trusted key, correct archives, missing-target rejection, Android original-certificate requirement and no unwanted desktop/mobile policy overwrite.
- [ ] Implement one PowerShell build orchestrator for desktop 0.4.4 and Android 1.2.3/versionCode 10, deriving minimum requirements from verified current metadata instead of resetting release sequence. Download and verify runtime archives with existing offline-cache recovery if needed; never disable checksum or signature checks.
- [ ] Build Windows with existing public key, then use the existing explicit human local manifest-signing step. Original private keys are not read automatically. Android unsigned output may be staged now; final original-certificate signing is a human step unless a user-controlled hidden prompt can be used.
- [ ] Produce SOURCE/WEB bundle from committed sources, exclude private/signing/.env data and stale installers. Use checked archive file lists and safe retry if Windows files are temporarily locked.
- [ ] Provide one complete PowerShell workflow for human build/sign, upload, backup and isolated restore test, additive migration, controlled API restart/health, reviewed inventory apply and signed publication. No cloud cleanup and no resetting account policy. Stop safely on failures; do not restore old schema blindly.
- [ ] Run Python/script/Node release tests and PowerShell parser checks, self-review and commit only task-owned artifacts.

## Task 5: Integration verification, build artifacts and handoff

**Files:** delivery folder F:/溪泉洗浴系统/最新版安装包-库存升级-0.4.4, release verification report and deployment instructions; source changes only to fix reviewed findings.

**Interfaces:** Consumes Task 1–4 commits and manifests. Output six EXEs, official original-signed APK if human signature available, SOURCE/WEB archive, hashes, instructions; otherwise explicitly label the remaining signing/install validation step and never pass an unsigned/test-only binary as a release.

- [ ] Execute full server, client, mobile and changed scripts test suites, renderer/native builds and six-target compatibility smoke checks. Compare assertions to spec line by line.
- [ ] Run a final whole-change security and correctness review with the complete task diff and reports; address important findings using a single scoped fix task and covering tests.
- [ ] Execute safe local Windows builds; check actual executable identity/arch. Build Android unsigned if certificate prompt cannot be completed by user in this session; provide the exact original-cert local signing/build command, not a replacement certificate.
- [ ] Gather only freshly verified artifacts into the new output folder; produce SHA256 manifest from actual files. Verify counts, versions and target metadata; report missing artifacts honestly rather than copying older versions.
- [ ] Record actual test/build results, limitations (Win7/Win10 unavailable machines, cloud deployment and hidden signing prompt) and inventory review gaps, without claiming cloud or real-machine completion.
- [ ] Finish development branch without merge/push/delete of unrelated user changes; deliver links and complete PowerShell instructions. Remaining user-controlled external actions are clearly separate from completed local implementation.
