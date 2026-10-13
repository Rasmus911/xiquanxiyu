# Desktop 0.4.9 Registration Implementation Plan

> **SUPERSEDED / DO NOT EXECUTE:** This draft describes the previous SMS design. The user replaced it with shared mobile authorization codes rotating every 180 seconds. Rewrite the plan after approval of the updated design specification; do not implement SMS registration from this draft.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver desktop 0.4.9 with maximized startup and securely administrator-approved staff registration, preserving business data and existing signed updates.

**Architecture:** Add a persistent registration challenge and global rate gate beside the existing Flask authentication service. Reuse Argon2 employee hashes, Aliyun SMS, authorization policy and audit barriers. Add an isolated Vue registration dialog and reuse the existing signed per-target Electron release pipeline.

**Tech Stack:** Flask, SQLAlchemy/Alembic, PostgreSQL 17/SQLite isolated tests, Vue 3, Element Plus, Vitest, Electron/NSIS, PowerShell 5.1.

**Spec:** `F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-08-desktop-049-registration-design.md` (approved in chat).

## Global Constraints

- Work in the user-designated `F:/溪泉洗浴系统` on the existing feature branch, preserve all unrelated untracked files; no additional working-tree copy under this directory.
- Never clear orders, members, stored balances, pass cards, stock, administrator bindings, or audit evidence.
- Public registration accepts only `male_scrubber`, `female_scrubber`, `floor_attendant`, ASCII `^1[0-9]{10}$` usernames, nonempty names (at most80 characters), existing 8–128 character password policy.
- Server forces active accounts and `allowed_channels=['desktop']`; no login token is issued by registration. No other pages or visit activation grants.
- Registration SMS recipient is fixed `18603346509`, independent of `SMS_ADMIN_PHONE`; template config is `SMS_REGISTRATION_TEMPLATE_CODE`, parameter `code`.
- Code expiry120 seconds after successful provider submission, global60 second cooldown, at most10 attempts/hour and30/day,5 wrong attempts/challenge. No plaintext code/password in DB, API responses, audit or logs.
- Release0.4.9, targets Win10/Win11 x86/x64 only; release notes exactly `新增 账号注册功能`. Keep original signing trust and increment live publication sequences; never guess sequence1.
- No cloud migration/publish, real SMS or GitHub asset removal without relevant verified prerequisites and authority. No new APK is requested in this release.
- Archive safe source/EXEs by version on the named public GitHub repo; retain keys, backups and real business data privately. Move historical local files recoverably only after remote verification and dependency preservation.

## Task 1: Persistent secure registration API and member SMS regression

**Files:** Create `server/app/registration_service.py`, `server/tests/test_registration.py`, `server/tests/test_registration_migration.py`, `server/migrations/versions/20261008_staff_registration.py`; modify `server/app/models.py`, `server/app/api/auth.py`, `server/app/config.py`, `server/app/serializers.py`, `server/app/schema_maintenance.py`, `server/tests/test_members_and_audit.py`, `deploy/cloud/docker-compose.prod.yml`, `deploy/cloud/.env.example`, `server/.env.example`, and focused runtime-role grants if necessary.

**Interfaces:** `POST /api/auth/registration-code` accepts `{username,display_name,role,password,terminal_code,client_channel:'desktop'}` and returns `{challenge_id,expires_at,resend_after_seconds:60,recipient:'186****6509'}` inside existing success envelope. `POST /api/auth/register` accepts `{challenge_id,code,terminal_code,client_channel:'desktop'}`, returns `{username}` plus a login instruction. Unknown fields and non-desktop channels are rejected; expired or consumed codes fail. New schema head `20261008_staff_registration` follows `20261007_ordering_cost`.

- [ ] RED: Write a route integration test proving a submitted code to the fixed recipient creates an active desktop-only employee, without registration tokens:

```python
def test_registration_creates_only_desktop_staff(client, app, strict_owner_session, monkeypatch):
    app.config['SMS_REGISTRATION_TEMPLATE_CODE'] = 'SMS_FIXTURE_ONLY'
    sent = []
    def send(phone, template, params, recipient):
        sent.append((phone, template, params, recipient))
        return {'success': True, 'status': 'sent', 'message': 'submitted'}
    monkeypatch.setattr('app.registration_service.send_template_sms', send)
    response = client.post('/api/auth/registration-code', json={
        'username':'13800000001', 'display_name':'测试师傅', 'role':'male_scrubber',
        'password':'fixture-password-123', 'terminal_code':strict_owner_session['terminal_code'],
        'client_channel':'desktop'})
    assert response.status_code == 200
    assert sent[0][0] == '18603346509'
    payload = response.get_json()['data']
    result = client.post('/api/auth/register', json={
        'challenge_id':payload['challenge_id'], 'code':sent[0][2]['code'],
        'terminal_code':strict_owner_session['terminal_code'], 'client_channel':'desktop'})
    assert result.status_code == 201
    assert result.get_json()['data'] == {'username':'13800000001'}
```

- [ ] Run `server/.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_registration.py -q` and retain expected missing implementation failure.
- [ ] Implement service with validated request dictionaries, fixed recipient, random six-digit codes, HMAC challenge-bound digests, Argon2 pending password hashes and transactional employee creation. Persist a seeded singleton rate-gate row and attempts; serialize global cooldown/counter reservation. Commit reservation before SMS call, activate only on confirmed success, invalidate replaced challenges without overwriting used history. Enforce 120sec expiry and5 failure attempts under row lock. SQLite tests must not use a cloud URL; PostgreSQL locks and grants must be explicit.
- [ ] Add migration that creates only challenge/rate tables and seed row. Reapply necessary barrier guards and least-privilege grants, don't alter business state or administrator UUIDs. Registration tables are not period-scoped business rows and must not be included in financial resets.
- [ ] Test bad role/phone/fields/channel/terminal, disabled terminal, missing template, SMS rejection/exception, expired/exact-boundary/used codes, wrong-code cap, global cooldown/hour/day limits including failed sends, duplicate and deleted username, changed registration attempt, concurrency lock contract and absence of plaintext secrets. Test staff desktop login and denial of mobile/web/admin/member/stock/report/visit-open endpoints under strict policy.
- [ ] Extend member SMS tests for financial idempotency and provider failure without duplicate money/card writes; mock only the external SMS provider boundary.
- [ ] Run focused tests, then `python.exe -m pytest -p no:cacheprovider -q` once; record results and skipped external prerequisites.
- [ ] Commit task-owned files only and report RED/GREEN, changed files, public interfaces, migration/grant specifics and concerns to the task report file.

## Task 2: Desktop registration dialog and maximized startup

**Files:** Create `client/src/components/auth/RegistrationDialog.vue`, `client/src/components/auth/RegistrationDialog.test.ts`, `client/src/auth/registration.ts`, `client/src/auth/registration.test.ts`; modify `client/src/views/LoginView.vue`, `client/electron/main.cjs`, `client/electron/main.node-test.cjs`.

**Interfaces:** Dialog props `{terminalCode:string}` emits `registered(username:string)` and uses existing API envelopes/error helpers from `client/src/api/http.ts`. API request contracts are exactly Task1's. Parent shows “注册账号” only when `window.xiquan` exists; fills login username and keeps password blank on success. Existing update button must remain available while logged out.

- [ ] RED: Extend the real main VM test double with `maximize()` and recorded show order; emit `ready-to-show` and assert maximize precedes show, while print-window behavior is unchanged.

```javascript
test('main starts maximized before showing without fullscreen', async () => {
  const f = await fixture()
  try {
    f.windows[0].emit('ready-to-show')
    assert.deepEqual(f.calls.slice(-2), ['maximize', 'show'])
    assert.notEqual(f.windows[0].options.fullscreen, true)
  } finally { f.close() }
})
```

- [ ] Run `node --test electron/main.node-test.cjs`, observe expected missing maximize behavior, implement ready-to-show maximize then show.
- [ ] RED: Mount the real registration dialog, fill valid fields, receive challenge from a mocked HTTP boundary, submit matching code and assert emitted username. Verify edit invalidation, challenge expiry/cooldown UI, restricted role choices, invalid phone/password mismatch, duplicate submissions and stale response after close/unmount.
- [ ] Implement Vue form with labels, keyboard submit, clear pending credentials on close/complete, pending-call generation guard and disabled double-submit. Send all details only when requesting a new challenge. Confirmation request uses challenge_id/code/terminal/channel only; do not send mutable role or password again.
- [ ] Test registration button desktop-only using a real login view where practical; don't replace entire component logic with mocks. Existing terminal setup, login and update remain intact.
- [ ] Run focused Vitest and Electron tests, type-check and full client tests once; commit only task files and report results.

## Task 3: 0.4.9 source, deployment, signed update and SMS handoff tooling

**Files:** Create `scripts/build-desktop-049.ps1`, `scripts/sign-desktop-049.ps1`, `scripts/invoke-desktop-049.ps1`, `scripts/desktop-049-deploy-entry.ps1`, `scripts/desktop-049-publish-entry.ps1`, `deploy/cloud/scripts/desktop_049_guard.py`, `deploy/cloud/scripts/desktop_049_deploy.py`, `scripts/tests/test_desktop_049_guard.py`, `scripts/tests/test_desktop_049_source.py`, `docs/releases/2026-10-08-desktop-049.md`; modify `client/package.json`, `client/package-lock.json`, `scripts/lib/source-security.cjs`, and update compatibility regression tests.

**Interfaces:** Reuse `desktop_048_deploy.py` / stock maintenance library through a focused release wrapper where safe; 0.4.9 should accept current schema `20261007_ordering_cost` and already-migrated `20261008_staff_registration`, snapshot stable business records, and validate challenge tables/grants after migration. Don't run previous cost/catalog business replacement again. Signed desktop profiles remain existing target-specific feed URLs and original key ID.

- [ ] RED: Test the release guard with literal old/new schema manifests and business snapshots; require additive registration structures and preserved financial/employee/stock/audit evidence. Run existing guarded workflow tests via fake infrastructure, not real SSH.
- [ ] Implement wrapper by reusing existing backups and offline-image build, dynamic low-memory checks and guarded maintenance release. Diagnose concrete private logs on failures, keep checkpoints and don't automatically clear maintenance or start an old image on new schema.
- [ ] Add source allowlist entries for new scripts; test source bundle contains exact new helpers and excludes secrets.
- [ ] Copy original public key into a version-neutral tracked-safe build trust path or explicitly preserve original key dependency, verify same bytes/key ID before using; do not read private signing key. Keep current offline runtime cache so no Electron downloads are needed.
- [ ] Set client version0.4.9 mechanically in package metadata. Build script emits four installers, source/web ZIP, delivery JSON, full Chinese PowerShell deployment/sign-publication entry points, and notes exactly `新增 账号注册功能`. Sign script reads verified live sequences, takes original private key path only on user machine, preserves global and per-target policy compatibility, never resets counters.
- [ ] Add upgrade regression covering released0.4.4–0.4.8 adapters reading and downloading a valid signed0.4.9 artifact for Win10/11 targets; check earlier0.4.0–0.4.3 adapter compatibility from stored source snapshots and report actual bounds.
- [ ] Document registration template `SMS_REGISTRATION_TEMPLATE_CODE`, Aliyun signature/credential presence checks without printing values, fixed recipient separation and real handset acceptance. Missing template blocks registration but not existing login/commerce.
- [ ] Run guard/source/compatibility tests and dry-run local scripts; commit only task-owned files and report exact invocation commands.

## Task 4: Build deliverables, archive verification and recoverable tidy

**Files:** Generated `最新版安装包-账号注册-0.4.9/*`; external staging under `F:/溪泉GitHub归档工作`; progress evidence under this plan's ignored workspace. Use existing sanitized archive scripts, keep all private signing files and production backups out of GitHub.

- [ ] Build committed0.4.9 renderer and four EXEs with original public trust and verified offline runtime bytes:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\build-desktop-049.ps1'
```

- [ ] Inspect each EXE's version/target payload, record SHA256, test source ZIP manifest and current entrypoint parser. Never call local unsigned delivery an online update; signing and cloud publication are separate explicit steps.
- [ ] Use the named GitHub Desktop repository clone to push reviewed latest sanitized source and source snapshots by version. Use GitHub Releases for large files and compare remote digests/sizes to `public-catalog.json` before any corresponding local move. Hand off authentication/security warnings or persistent upload blockers to the user.
- [ ] Keep latest release folder and necessary source/dependencies in project. Move verified historical friendly folders, superseded release artifacts and private history into explicit project-external version-classified directories using validated `Move-Item -LiteralPath`; no recursive delete, no removal of `.git`, migrations or unreviewed user files. Preserve or repoint trust/cache paths first.
- [ ] End with latest deliverable path, complete deployment/update PowerShell, SMS prerequisites, actual archive/tidy verification report and any unfinished external steps; don't claim cloud, SMS delivery or archives completed without evidence.

## Plan Review and Execution

The user explicitly selected continued development in this session. Use task-scoped subagent implementation and review where supported; implementation tasks run sequentially to avoid shared-index conflicts. Shared interfaces: Task1 produces API shapes consumed by Task2 and schema consumed by Task3; Task3 produces signed-ready artifacts consumed by Task4. No implementation needs a separate user approval between tasks; real credentials, protected actions and irreversible operations retain their approval boundaries.
