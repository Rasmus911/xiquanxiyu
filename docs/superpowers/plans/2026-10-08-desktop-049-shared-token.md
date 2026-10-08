# Desktop 0.4.9 Shared Registration Token Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver desktop 0.4.9 with maximized startup and limited staff registration authorized by the same 180-second token displayed on two administrators' phones, with signed upgrades and recoverable historical archiving.

**Architecture:** Add persistent registration authorization, rate limits and idempotency beside Flask authentication. Only existing UUID-protected mobile administrators can read the server-generated token; public registration consumes one authorization in the same transaction as ordinary staff creation. Vue clients consume fixed API contracts; additive deployment and original-trust release tools preserve the working database.

**Tech Stack:** Flask, SQLAlchemy/Alembic, PostgreSQL 17, isolated SQLite tests, Vue 3, Element Plus, Vitest, Electron/NSIS, Capacitor Android, PowerShell 5.1, GitHub Desktop.

**Spec:** `F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-08-desktop-049-registration-design.md`, approved by the user after commit 4014705.

## Global Constraints

- Desktop version `0.4.9`; targets `win10-x86`, `win10-x64`, `win11-x86`, `win11-x64`; no Win7 output.
- Android version `1.2.7`, versionCode `14`, minimumVersionCode `9`; original signing certificate only, original application ID and in-app download/cover installation.
- Public desktop release notes exactly `新增 账号注册功能`.
- Shared six-digit token automatically changes every `180` server seconds; successful registration immediately consumes and changes it, starting another 180 seconds.
- Only UUID-protected active existing accounts `18603346509` and `18631459666` with mobile sessions may view it; `15133863898` and all other accounts must not view it.
- Registration accepts only ASCII Chinese phone pattern `^1[0-9]{10}$`, employee name, password and roles `male_scrubber`, `female_scrubber`, `floor_attendant`; server fixes `is_active=True`, `allowed_channels=['desktop']`.
- New staff can only see active wristbands and add orders; no opening, clearing, financial, membership, inventory, report or administration grants.
- Dedicated server `REGISTRATION_TOKEN_SECRET` has at least 32 bytes; missing/invalid config disables this feature, not the entire API. No registration SMS, universal code or shipped secret.
- Keep membership SMS behavior and all existing orders, members, balances, pass cards, stock, audit and account bindings. No destructive reset or old-API restart against a migrated schema.
- Maintain append-only audit, maintenance barriers, least-privilege runtime grants, persistent throttling and transactionally one-use authorization.
- Original desktop update trust and per-target feeds remain; logged-out login page can check/download updates. Verify actual old-version compatibility, do not claim unverified universal compatibility.
- Work in the user's current feature checkout `F:/溪泉洗浴系统`; preserve unrelated untracked files, nested repositories and private state. Only explicit task files are staged.
- Public source upload uses GitHub Desktop to `https://github.com/Rasmus911/xiquanxiyu`; historical binaries belong in Releases classified by version. Public artifacts exclude credentials, certificates/private keys, `.env`, database dumps and real business data.
- Only move old local originals after the corresponding GitHub artifact is verified; failed builds/caches/private evidence can be classified in an external recoverable directory, not falsely described as uploaded.
- No cloud mutations, real SMS, credential access or publication from an implementation/review worker. Human-run deployment/signing commands are the release boundary.

---

### Task 1: Persistent one-use authorization and limited registration API

**Files:**
- Create: `server/app/registration_access.py`, `server/app/registration_models.py`, `server/app/registration_service.py`, `server/app/api/registration.py`.
- Modify: `server/app/models.py` (model registration only), `server/app/api/__init__.py`, `server/app/config.py`, `server/app/employee_access.py`, `server/app/database_guards.py`, `server/app/serializers.py`.
- Create: `server/migrations/versions/20261008_registration_token.py` following `20261007_ordering_cost`.
- Modify: `server/.env.example`, `deploy/cloud/.env.example`, `deploy/cloud/docker-compose.prod.yml`, `deploy/cloud/scripts/runtime-role.sql` for the new server-only setting and grants; never actual `.env`.
- Test: `server/tests/test_registration049.py`, `server/tests/test_registration049_migration.py`; existing auth, employee, barrier and member SMS suites.

**Interfaces:**
- Consumes current Employee, Terminal, active UUID policy, current_employee, hash_password, write_audit, db.session and maintenance barriers.
- Produces `registration_access.can_view_registration_token(employee, channel) -> bool`; false unless all username, active/deleted/role, protected UUID and mobile checks pass.
- Session `employee.capabilities.registration_token_view` is boolean and re-evaluated by the server on login/me/refresh. It is not itself endpoint authorization.
- `POST /api/auth/registration-token/current`: authenticated mobile-only; normal envelope data `{code: string, generation: integer, server_time: UTC ISO string, expires_at: UTC ISO string}`; `Cache-Control: no-store`.
- `POST /api/auth/register`: JSON `{username, display_name, role, password, code, terminal_code, client_channel:'desktop'}`; required `Idempotency-Key` header. Success 201 with safe employee identity, no tokens/password hash. Idempotent retry returns original identity without another authorization consumption.
- Errors include `REGISTRATION_CODE_INVALID`, `REGISTRATION_RATE_LIMITED`, `REGISTRATION_NOT_CONFIGURED`, `REGISTRATION_FORBIDDEN`; malformed/extra fields return 400, unregistered terminal 403, duplicate username 409. Error text is Chinese, details never include submitted passwords/codes.
- Schema head `20261008_registration_token`; ordinary API startup never migrates automatically.

- [ ] **Step 1: Write a failing endpoint behavior test and strict-policy fixtures.** Rename two existing protected fixture administrators to the specified usernames, use mobile login tokens, and keep all production fixture data isolated.

```python
def test_same_token_and_single_use(app, client, registration049_sessions):
    first = client.post('/api/auth/registration-token/current',
                        headers=registration049_sessions['first']).get_json()['data']
    second = client.post('/api/auth/registration-token/current',
                         headers=registration049_sessions['second']).get_json()['data']
    assert first['code'] == second['code']
    assert first['generation'] == second['generation']
    body = dict(username='13900001234', display_name='隔离员工', role='male_scrubber',
                password='fixture-staff-password', code=first['code'],
                terminal_code='ENTRY-TEST', client_channel='desktop')
    created = client.post('/api/auth/register', json=body,
                          headers={'Idempotency-Key': 'registration-fixture-1'})
    assert created.status_code == 201
    assert created.get_json()['data']['allowed_channels'] == ['desktop']
    body['username'] = '13900001235'
    reused = client.post('/api/auth/register', json=body,
                         headers={'Idempotency-Key': 'registration-fixture-2'})
    assert reused.status_code == 403
```

- [ ] **Step 2: Verify RED.** Run from server: `./.venv/Scripts/python.exe -m pytest tests/test_registration049.py -q -p no:cacheprovider`. The registered endpoint must fail for missing behavior before any implementation; retain relevant output.
- [ ] **Step 3: Implement isolated registration units and additive migration.** Keep HMAC generation and access checks separately testable; use a database row lock for shared state and a SQLite-compatible compare-and-swap or explicit write serialization, never only a process-local mutex. Inputs are strictly typed/whitelisted. Existing Argon2 enforces 8–128 password characters. Never accept role or channel from an idempotency receipt that was not created by this service.

```python
# Service transaction ordering, not an alternate unguarded endpoint:
# acquire existing maintenance shared barrier
# validate desktop terminal, field types and request-key digest
# lookup matching successful receipt (return safely on exact retry)
# lock shared authorization state, normalize expired generation
# enforce persistent terminal/source limits and current-generation failure cap
# constant-time compare dedicated-secret-derived code
# add enabled desktop-only Employee, consume generation, create distinct new code
# write receipt + append-only audit and commit atomically
```

The server derives a code from a non-secret persisted seed/generation and dedicated secret, never persists plaintext. Reject a new code equal to its immediate predecessor. Stable HMAC request digest prevents ordinary password-hash dictionaries in idempotency records. Invalid attempts commit their counters before raising a response; attempted registrations cannot roll counters back. Rate gates: each terminal and trusted source at most 10 verification attempts per 10 minutes; one generation at most 5 wrong codes before expiry. Admin token viewing cannot reset those counters. View audit is deduplicated per session/generation; logs cannot infer a unique approver from a shared code.

- [ ] **Step 4: Extend behavior tests.** Controlled time proves valid at second 179 and invalid at 180, successful rotation and restart persistence; constant-time checking/one-use races; expiry and idempotency; invalid phone, name, role and extra privilege fields; disabled/deleted/spoofed username/unprotected UUID/non-mobile/third admin denial; maintenance blocks writes; lack of secret leaves health/login usable; no code/password in audit responses; staff desktop permissions and mobile/web denial. Migration must preserve business snapshots and install grants/barriers/immutable receipts without deleting existing tables.
- [ ] **Step 5: Verify GREEN and bounded regressions.** Run registration tests then existing auth, access, employee lifecycle, barrier, member SMS tests once, not after every edit. Record exact commands/results, migration head and public contracts in the report.
- [ ] **Step 6: Commit only Task 1 files.** `git diff --check`; `git add -- <explicit listed paths>`; `git commit -m "feat: authorize desktop staff registration with shared mobile token"`.

### Task 2: Desktop registration, maximized startup and secure phone token page

**Files:**
- Create: `client/src/components/auth/RegistrationDialog.vue`, `client/src/components/auth/RegistrationDialog.test.ts`, `client/src/domain/auth/registration.ts`, `client/src/domain/auth/registration.test.ts`.
- Modify: `client/src/views/LoginView.vue`, `client/electron/main.cjs`, `client/electron/main.node-test.cjs`, `client/package.json`, `client/package-lock.json`, compatible update integration tests in `client/electron/updater.node-test.cjs`.
- Create: `mobile/src/views/RegistrationTokenView.vue`, `mobile/src/views/RegistrationTokenView.test.ts`, `mobile/src/registration/token-state.ts`, `mobile/src/registration/token-state.test.ts`.
- Modify: `mobile/src/views/ProfileView.vue`, `mobile/src/router/index.ts`, `mobile/src/router/access.ts`, `mobile/src/router/access.test.ts`, `mobile/src/mobile-management.ts`, `mobile/src/types.ts`, `mobile/src/business/state.ts` and native foreground wiring only where necessary; `mobile/version.json`.

**Interfaces:**
- Consumes Task 1 endpoints, data types, error codes and server-issued `registration_token_view` capability.
- Produces desktop form that emits registered username to LoginView, uses a retained random Idempotency-Key only for retries of the same submitted data, clears passwords/code on close/success, and ignores responses after unmount/session change.
- Phone route `/registration-token` (`registration-token` route name); ProfileView link only when server capability true. Direct route guards and server endpoint remain mandatory.
- `TokenSnapshot = {code:string, generation:number, server_time:string, expires_at:string}`; `token-state.ts` supplies real countdown validation/expiry and latest-request ownership, not a hardcoded code.
- Desktop source version `0.4.9`; phone version `1.2.7` / versionCode `14` / minimumVersionCode `9`.

- [ ] **Step 1: Write failing real-component and lifecycle tests.** Submit the actual registration component to a controlled HTTP boundary; assert payload limited to three roles/desktop and safe UI results. Test an old response cannot reopen a closed dialog; code/password never go to storage. Extend real Electron VM harness to observe the ready-to-show callback, main-window maximize then show, and no maximization of receipt windows.

```ts
it('expired token is never displayed as usable', () => {
  const snapshot = { code: '123456', generation: 1,
    server_time: '2026-10-08T00:00:00Z', expires_at: '2026-10-08T00:03:00Z' }
  const state = acceptTokenSnapshot(snapshot, 1000)
  expect(tokenDisplay(state, 180999).remainingSeconds).toBe(1)
  expect(tokenDisplay(state, 181000).code).toBe('')
})
```

Define the two functions above in `token-state.ts`; count from a monotonic elapsed baseline corrected from server time, not phone wall-clock alone. Fake monotonic time only, no test-only methods in production classes.

- [ ] **Step 2: Verify RED.** `npm.cmd exec vitest run src/components/auth/RegistrationDialog.test.ts src/domain/auth/registration.test.ts` (client), focused mobile token tests (mobile), and `node --test electron/main.node-test.cjs` before maximize modification.
- [ ] **Step 3: Implement desktop UI and startup.** Registration button only in the Electron login page, preserve server/terminal setup, bootstrap and update button. Form labels in plain Chinese; validate ASCII phone, nonempty bounded name, three roles, 8–128 password and matching confirmation, six-digit code; show expired/rate-limit/config errors without discarding other fields. The code is administrator authorization, not SMS or proof of staff phone possession.

```js
mainWindow.once('ready-to-show', () => {
  mainWindow.maximize()
  mainWindow.show()
})
```

- [ ] **Step 4: Implement phone page and capability gating.** On active visible page read snapshot, poll no more than every5 seconds with a single in-flight request; immediately clear on failed request, offline, expiry, background, route leave, account/security generation change or logout. Foreground resumes only through a fresh authenticated query. Reject stale generations and stale request ownership; show actionable offline/expired notices. No token in localStorage/sessionStorage/service worker caches. Use existing security generation mechanism and Capacitor App lifecycle with cleaned-up listeners. Use narrow invalidate-only events if already practical; polling supplies bounded synchronization without adding global token broadcasts.
- [ ] **Step 5: Verify original update paths.** Run existing real per-profile updater adapters with old 0.4.4–0.4.8 metadata and new 0.4.9 signed fixtures; no universal global-feed fallback. Check pre-0.4.4 source if available and document actual compatibility. Do not invent an update hook absent from an installed binary. Existing phone UpdateGate must show/download newer policy without webpage redirect.
- [ ] **Step 6: Verify GREEN/type builds and commit.** `npm.cmd test` and `npm.cmd run build` in each frontend; relevant Electron tests. `git diff --check`; commit only this task's files with `feat: add desktop registration and administrator mobile token page`.

### Task 3: Exact-source additive cloud deployment and original-trust release tools

**Files:**
- Create: `scripts/build-desktop-049.ps1`, `scripts/sign-desktop-049.ps1`, `scripts/invoke-desktop-049.ps1`, `scripts/desktop-049-deploy-entry.ps1`, `scripts/desktop-049-publish-entry.ps1`, `scripts/desktop-049-android-entry.ps1`.
- Create: `deploy/cloud/scripts/desktop_049_guard.py`, `deploy/cloud/scripts/desktop_049_deploy.py`, `deploy/cloud/scripts/android_127_publication.py`.
- Test: `scripts/tests/test_desktop_049_guard.py`, `scripts/tests/test_desktop_049_entrypoints.py`, `scripts/tests/test_desktop_049_source.py`, `scripts/tests/test_android_127_publication.py`.
- Modify: `scripts/lib/source-security.cjs` / relevant allowlist tests, shared cloud helper only if a narrowly tested extension avoids copying existing unrelated business conversion routines.
- Create: `docs/releases/2026-10-08-desktop-049.md`.

**Interfaces:**
- Consumes reviewed committed source, schema `20261007_ordering_cost`, migration head `20261008_registration_token`, existing `stock_deploy`, backup verification and safe low-memory/offline image infrastructure.
- `build-desktop-049.ps1`: `-PublicKeyPath`, `-OfflineRuntimeCache`, `-OutputDirectory`, `-BuildId`, `-DryRun`; four Windows targets; output `交付信息.json` with ProjectRoot, ReleaseRoot, OutputDirectory, SourceCommit, SourceZipFile, SourceSha256, Version, Targets, CloudChanged=false, UpdateSignature status.
- `invoke-desktop-049.ps1`: `-Mode preflight|deploy|resume|all`, `-BundlePath`, `-ExpectedSha256`, `-SourceCommit`, optional `-Stage`, `-Job`, `-EcsTarget`, `-StageOnly`; parse a verified exact private stage automatically, no copy-paste stage question.
- Stage prefix `/opt/xiquan-releases/desktop049-stage-`; job prefix `/opt/xiquan-backups/desktop049-cutover-`; preserve job/evidence on failure and emit specific named phase.
- Chinese delivery scripts: `01-部署云端.ps1`, `02-签名并发布桌面更新.ps1`, `03-构建并发布安卓应用内更新.ps1`.

- [ ] **Step 1: Write failing executable guard/source tests.** Use isolated database fixtures/controlled remote subprocess boundaries, not greps of source text. Verify unexpected schema, wrong image/source hashes, changed business snapshot and insufficient resources stop before production API stop. Verify HEAD migration does not change balances/pass ledgers/stock/account grants. Exercise PS StageOnly/DryRun with valid and invalid bundle fixtures and assert no SSH invocation.

```python
def test_guard_rejects_unexpected_head(guard_fixture):
    guard_fixture.schema = '20260827_visit_party_link'
    with pytest.raises(DeploymentError):
        registration_guard_preflight(guard_fixture)
    assert guard_fixture.api_stops == 0
    assert guard_fixture.database_writes == 0
```

Define the controlled fixture and guard function through the production guard boundary, following existing 048 guard tests; the fixture must not replace the validation under test.

- [ ] **Step 2: Verify RED.** Run the four new test files with bundled server Python; retain expected missing-feature failure.
- [ ] **Step 3: Implement additive guarded release.** Reuse existing verified backup, isolated PG17 restore, pinned offline dependency image and checkpoint machinery. Do not replay service catalog conversions, material imports, account activation or data resets. Add only registration schema and grants. Secret setup generates a safe value in the private remote environment if absent, preserves an existing valid value, makes a private permission-restricted backup, never prints the secret; source examples contain placeholders only. Resume distinguishes pre-migration/post-migration/API-start phases and never blindly applies an old restore or repeats data mutation.

```python
# Deployment order:
# validate exact source + live supported schema + active policy + no conflicting reset
# build/verify pinned offline image before stopping healthy API
# verified private backup and isolated additive migration rehearsal
# owned maintenance, production migration, prove unchanged business/account snapshot
# source/assets switch, start pinned API, resolve nginx upstream, check health and config
# release owned maintenance, verify normal worker and registration capability config
# write completed receipt (do not publish EXE/APK feeds here)
```

Low-memory checks use existing maintenance/restore limits and documented available memory, not a new impossible 2GiB requirement. Private subprocess logs are retained but console errors must identify phase/error category rather than hide every failure behind one generic line. Preserve historical stock images/keys until needed references are relocated.

- [ ] **Step 4: Implement build/sign/publication entrypoints.** Build from committed reviewed tree with cloud API URL; retain original desktop Ed25519 trust and increasing per-target sequence derived from verified live policies. Android previous certificate SHA256 remains `15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9`; use hidden local password input and previous original-signed APK validation. No account passwords embedded in PS code. Create no new certificate or signing root. Android build-only and publish phases must be separately possible; no upload if build/signature/version/hash checks fail. Separate source/web deployment success from signed-feed publication success.
- [ ] **Step 5: Put all instructions in delivery docs.** Use `powershell.exe -NoProfile -ExecutionPolicy Bypass -File` (works with restricted default policy); no CMD/Bash mixed syntax. Explain typed confirmation, where install/update UI is, exact versions and no production clearing. Public notes exactly one requested line. Preserve API restore worker guards.
- [ ] **Step 6: Verify tests, dry-run/source inclusion and commit.** New guard/source tests, existing helper tests covering touched code, PowerShell parser/DryRun, source-security tests, `git diff --check`; commit `build: add guarded 0.4.9 registration release and update publication`.

### Task 4: Build delivery, verified version archive and recoverable local tidy

**Files/artifacts:**
- Generate: `F:/溪泉洗浴系统/最新版安装包-账号注册-0.4.9` from Task3 builder; committed release verification report `docs/releases/2026-10-08-desktop-049-verification.md`.
- Public archive clone: `F:/溪泉洗浴系统/Clone/xiquanxiyu` (separate repository), external preparation `F:/溪泉GitHub归档工作`.
- Update public `archive/versions.json` and version-specific manifests/source snapshots, sanitized current source only. Do not push private main repository history.

**Interfaces:**
- Consumes four committed EXEs, exact SOURCE/WEB ZIP, original trust/public key, mobile signing entrypoint, canonical history hashes and actual GitHub upload receipts.
- Produces delivery paths/SHA256, recorded verified GitHub versions and external recoverable move manifest. Reports pending original-certificate build/publish or failed UI upload honestly.

- [ ] **Step 1: Run Task3 builder against available pinned runtime cache.** Use `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop-049.ps1`; skip no required trust check. Confirm four artifacts' actual architecture/version from package receipts and renderer asar. Copy no unsigned APK into a formal slot. Preserve original signing key paths until safe version-neutral public dependencies are checked.
- [ ] **Step 2: Record artifact facts and commands.**

```powershell
Get-ChildItem -LiteralPath 'F:\溪泉洗浴系统\最新版安装包-账号注册-0.4.9' -File |
    Where-Object { $_.Extension -in @('.exe', '.apk', '.zip') } |
    Get-FileHash -Algorithm SHA256
```

File presence is not proof of a signed online release. Delivery report separates built, signed, uploaded, cloud-deployed and real-device-tested states.
- [ ] **Step 3: Archive public-safe source via the requested GitHub Desktop app.** Read current computer-use skill/references before any native UI action. Use existing sanitized public clone/remote. Scan staged diff for excluded private files before committing; explicitly stage only reviewed public source and version manifests. GitHub Desktop Commit/Push according to user scope; verify remote commit. Historical source ZIPs classify by desktop version; binary Releases keep exact original file hashes and relevant Android versions. Existing 0.4.3 release is already verified; do not upload it again.
- [ ] **Step 4: Verify each newly uploaded GitHub archive before moving its local original.** If UI/runtime cannot reliably complete large uploads, retain original versions and record the actual blocked versions, never claim they were archived. Use permission-scoped recoverable moves only after exact source/target resolution, no recursive project delete. `.git`, migration chain, live development environments, current release prerequisites and private signing files remain usable.
- [ ] **Step 5: Verify package hashes and clean reviewed source, commit release report.** Final whole-feature review precedes external publish/cleanup. Report precise installed upgrade path, Android original-cert command, cloud command and remaining user actions; do not stop on an optional cosmetic difference.
