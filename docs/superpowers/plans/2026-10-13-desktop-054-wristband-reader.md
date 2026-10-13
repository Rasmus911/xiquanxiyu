# 0.5.4 Wristband Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户指定单代理、原目录开发；保留现有未提交的 0.5.3 文件，不另建工作树。

**Goal:** 云端绑定 100 个手牌芯片，前台刷卡一次开牌，成功新开牌在滚动 60 秒内联动。

**Architecture:** 绑定及接收会话存储于服务器；复用财务串行锁、经营期屏障、幂等记录、门票创建与审计。前端用独立快速数字接收器和串行队列；路由/弹窗/身份变化停止接收，不离线重放。

**Tech Stack:** Flask/SQLAlchemy/Alembic/PostgreSQL17、Vue3/TypeScript/Vitest、Electron 原签名发布工具、Capacitor Android。

**Spec:** `docs/superpowers/specs/2026-10-13-desktop-054-wristband-reader-design.md`

## 执行状态（2026-10-13）

Tasks 1–5 的实现、预期失败测试及本机回归已完成。后端909通过、1项需独立PG17而跳过；桌面Vue339通过，手机211通过。Task6发布/恢复工具已实现并检查，安装包构建及历史归档处理中。原密钥签名、云端PG17演练、线上全文验证和真实USB读卡器验收待用户执行，不能以SQLite或模拟更新测试替代。

按用户单代理要求统一提交当前最新版，未按每个任务单独提交；保留先前0.5.3未提交改动。下方逐步清单是设计原始执行步骤，云端/签名/实机步骤完成前保持开放。

## Global Constraints

- 0.5.4；Win10/Win11 x86/x64，不做 Win7；Android1.2.11/code18/minimum9，原证书。
- 发布日志原文：`1.用ID卡读取手牌号来实现开牌的效果`。
- 男001–050、女051–100；不重新编号、不清空业务；经营重置保留物理绑定。
- 仅 cashier 和 UUID 策略绑定的最高权限人员维护绑定；不授予库管或手机。
- 新迁移 `20261013_wristband_chip` 接续 `20261012_physical_membership`。
- 不连接 ECS；本机签名密码隐藏输入；实机验收和线上验证不得假称完成。
- 原签名、TLS、SHA256、单调更新序号全部保留；网页资源前缀 `/app/`。

## Task 1: Binding storage, permissions and additive migration

**Files:** `server/app/models.py`、`server/app/auth_service.py`、`server/app/employee_access.py`、`server/app/api/__init__.py`；新增 `server/app/api/wristband_reader.py`、`server/app/wristband_reader_service.py`、`server/migrations/versions/20261013_wristband_chip.py`、`server/tests/test_wristband_reader.py`。

**Interfaces:** `GET /wristband-reader/bindings` -> active 100 rows `{wristband_id,number,bath_area,status,chip_uid,version,updated_at}`。`PUT /wristband-reader/bindings/<band_id>` body `{chip_uid,password?,version}`；`DELETE` body `{password,version}`。`can_bind_wristband(employee,channel)` -> bool。

- [ ] Write real fixture tests for cashier/highest access, denied inventory/service/mobile, 100 rows and leading-zero UID, duplicate UID, wrong password, busy band and stale version.

```python
response = client.put('/api/wristband-reader/bindings/' + band_id,
    headers=owner['headers'], json={'chip_uid':'000315346091','version':0})
assert response.status_code == 200
assert response.json['data']['chip_uid'] == '000315346091'
```

- [ ] Run `.\server\.venv\Scripts\python.exe -m pytest server/tests/test_wristband_reader.py -q`; require expected missing-route failure first.
- [ ] Implement unique UID and unique band constraints, locked version/password checks, audit and event; migrate with real PG role grants and guards, no destructive downgrade.
- [ ] Run tests plus existing access/employee tests; inspect diff and commit only new feature files/owned hunks.

## Task 2: Atomic scan admission and server-owned sliding session

**Files:** above service/API/test plus `server/tests/test_wristband_scan_session.py`.

**Interfaces:** `POST /wristband-reader/scan` body `{chip_uid,link_mode,session_id?,idempotency_key}` -> `{opened,wristband_number,visit_id,session:{id,expires_at,numbers}|null}`. `WristbandScanSession` stores employee, terminal, period, party, deadline and `{visit_id:wristband_id}` membership. `scan_wristband(employee,body)` executes under existing financial write lock; reuse `_create_visit` for authoritative ordinary ticket.

- [ ] Write opening/replay tests and session-boundary tests with controlled service clock.

```python
first = scan('001', link=True)
second = scan('051', link=True, session=first['session']['id'])
assert second['session']['numbers'] == ['001','051']
assert scan('001', link=True, session=second['session']['id'])['opened'] is False
```

- [ ] Observe failing scan route; implement idempotency lookup/store in same transaction and server timestamps, own-session identity checks, no merge of unrelated existing visits.
- [ ] Verify 59s join / 60s new group, repeated/unknown card not extend, settlement/clear/switch/manual-link invalidate, cross terminal denied and 100 scans supported.
- [ ] Run real isolated PostgreSQL tests when runtime available; otherwise retain explicit pending PG proof and require deployment rehearsal before production.

## Task 3: Keyboard burst receiver and serial queue

**Files:** new `client/src/domain/wristband-reader/keyboard.ts`, `queue.ts`, matching tests.

**Interfaces:** `createChipReceiver({onRead,canRead,maxGapMs,minDigits})` returns `{keydown,reset}`; `createScanQueue<T>(send,onResult,onError,limit)` returns `{enqueue,clear,pending}`. Queue assigns one immutable request identity per submission and rejects stale generation results.

- [ ] Test normal typing/Enter, fast digits/newline, leading zeros, editing/modals/hidden page, queue ordering, overflow, network error discard and reset while request in flight.

```ts
receiver.keydown(new KeyboardEvent('keydown',{key:'0'}))
receiver.reset()
expect(reads).toEqual([])
```

- [ ] Run `npx.cmd vitest run src/domain/wristband-reader`; observe missing behavior then implement focused modules. No global listener outside Dashboard.
- [ ] Run typecheck and neighboring keyboard tests, commit focused modules.

## Task 4: Binding page and server-authoritative navigation

**Files:** new `client/src/views/WristbandBindingsView.vue` and tests; modify `client/src/navigation/{menu,access}.ts`, `client/src/router/index.ts`.

**Interfaces:** `/wristband-bindings` page requires server `ui_pages` plus `capabilities.wristband_bind`; after settings, before account-password. GET and PUT/DELETE consume Task1 payloads; no scanning opens a visit here.

- [ ] Test navigation denied without cap and mapping table count/filter/save/read state.
- [ ] Implement selectable number, explicit scan/save dialog, first-bind vs change password, version conflict refresh, danger confirmation unbind.
- [ ] Verify input reset preserves zero digits and errors never clear previous valid mapping; run Vue tests/typecheck.

## Task 5: Dashboard scan and group status

**Files:** new `client/src/components/wristbands/WristbandReaderPanel.vue` and tests; modify `client/src/views/DashboardView.vue`.

**Interfaces:** panel props `{enabled,paused}` emits `changed` after success; uses Task2 endpoint, Task3 receiver/queue, displays link toggle/members/count/deadline. `paused` covers selection/edit/dialog; window-hidden and session-clear reset queue/session. Each request asserts captured business generation.

- [ ] Test admitted scan refreshes without route jump; not-open-cap staff have no listener; toggle off discards receiving context but doesn't unlink bills.
- [ ] Implement mounted keydown listener only while permitted Dashboard active. Preserve normal Enter/Tab/Esc; serialize submissions and clear on unmount/session/visibility/offline.
- [ ] Run relevant navigation/Dashboard/admission/checkout and mobile synchronization tests. Check existing manual max20 untouched.

## Task 6: Versioned delivery, cloud rehearsal, archive

**Files:** new `scripts/prepare-desktop-054.cjs`, `scripts/invoke-desktop-054.ps1`, `deploy/cloud/scripts/desktop_054_deploy.py` and guards/proof tests; delivery `最新版安装包-刷卡开牌-0.5.4`；版本/日志/部署注意事项；归档沿用验证过的分片工具。

- [ ] Test frozen SOURCE excludes private material, only target migration allowed, exact job resume rejects foreign images, source-aware PG17 proof authenticates request context, static checks use `/app/`, resource accounting and private backup ownership.

```python
assert target_revision == '20261013_wristband_chip'
assert source_commit == receipt['source_commit']
assert image_id == receipt['image_id']
```

- [ ] Adapt established checkpoint deployment, never rerun older production migration unconditionally. Document each phase and recovery action; all ECS operations remain user-run.
- [ ] Build four unsigned installers/web/mobile staging, obtain original-key signature through user's hidden local prompts, choose sequence above verified four channels/history; verify public bytes separately.
- [ ] Archive old public versions via requested GitHub Desktop with <=32MiB parts; remote content proof before deletion. Preserve latest source/dependencies/private keys/backups and blocked-delete evidence.
- [ ] Record local tests/builds vs pending signatures/online/device checks separately. Hand over absolute paths and complete PowerShell using `-ExecutionPolicy Bypass`, versioned manifest and exact stage/job identities.
