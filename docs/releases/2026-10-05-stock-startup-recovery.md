# Stock API startup checkpoint recovery

## Observed failure

Human-provided Docker diagnostics: API exited with code 1, OOMKilled=false,
deployment preflight passed. `run.py` called `recover_reset_tasks`, which rejected
the stock deployment's maintenance owner as conflicting reset evidence.
Available physical memory was 923 MiB. This is a startup sequencing bug, not an
OOM or a role-preflight failure.

Exact checkpoint: `/opt/xiquan-backups/stock-cutover-1b2ec99a92d041e5a846c1cf2c681592`.
Source: `c468e73486c864fb732b6d09987d1d23cf222cfe`.
Stage: `/opt/xiquan-releases/stock-stage-e983f550ba6d441b828ad8b54683946f`.
Pinned image: `sha256:576506ecd31f83624da696213c449ef6a460bbc2369dc0028d26509c80dad39f`.
Human confirmed ready.json and after.json exist; completed.json does not.

## Bounded correction

`stock_startup_recovery.py` wraps the original six unchanged verified tools and
supports only this checkpoint's resume. Original source hash, protected files,
configuration hashes, PG17/role/audit checks, exact after snapshot and maintenance
ownership gates remain active. No rebuild, migration, restore, installer
publication, importer, account change, database clearing or cleanup is added.

The initial Compose override pauses only RESET_WORKER_ENABLED. HTTP/SQL write
barriers remain enabled. After original guarded maintenance release, recreate
the same pinned API using its original image override and configuration, verify
health, normal environment and single-replica identity, then permit the original
completion receipt. Reset recovery and security spool import run at this final
normal startup. No permanent .env or compose edits are made.

If failure happens after lease release, normal-worker-restore-required.json and
phase records are retained; do not blindly rerun a maintenance-owned resume.
Future fresh deployments must adopt the corrected sequencing, not reuse this
checkpoint-specific recovery script.

## Limited local verification

The three startup ordering tests failed against the original finish workflow:
worker was enabled under maintenance and not explicitly restored after release.
The same three tests passed with the recovery wrapper. Docker/network operations
are external-boundary doubles; this is not a cloud or real PostgreSQL test.
Success, unhealthy initial API, and refused release are covered. The latter two
never release maintenance or write completed.json.

Windows PowerShell 5.1 StageOnly returned exit 0, local original bundle/tool
verification succeeded, and CloudChanged=false. Wrapper uses ASCII source text
and derives its project directory to avoid PowerShell UTF-8/no-BOM path corruption.

No agent SSH/SCP, cloud restart or migration was performed. Human cloud execution
and `STOCK_STARTUP_RECOVERY_OK` plus final public health are still pending.

## Follow-up Docker command evidence

The human retry stopped inside the Compose startup command, before health wait.
Compose config --quiet returned 0. The retained API exited 137 with OOMKilled=false;
Docker journal explicitly recorded SIGKILL after its SIGTERM stop deadline. This
is cleanup evidence, not the original Compose command's root cause. Do not label
it an OOM or claim that the Docker start failure has been resolved.

The recovery-only startup transport now preserves actual stdout/stderr/exit code
in a private 0600 compose-start-failure receipt and emits only a bounded redacted
Docker error block. UTF-8 decoding is explicit and replace-safe; startup is bounded
to 180 seconds. The six original checkpoint tools, source, image, private configs,
ownership/preservation gates and resume-only sequencing remain unchanged. No new
automatic retries or lease clearing are added. A focused diagnostic regression
failed before the change and passed afterward; the three ordering checks also
passed (4 total), with external Docker execution doubled locally. Actual ECS root
cause still requires the captured Docker error or successful final health.

## Retry evidence-file collision correction

A subsequent retry stopped before the paused-start phase. Local reproduction
with the already-existing startup-worker-paused.json raised FileExistsError:
json_write intentionally uses O_EXCL. Reusing a completed configuration file is
required for this ready-checkpoint retry, not overwriting/removing it. Recovery
now reads it through the existing no-links loader and requires the entire
service/image/environment payload to match; mismatches stop before Docker and
leave the original bytes unchanged. Two focused regressions reproduced the
collision/mismatch failures and passed after correction, as did the previous
four checks. This does not assert the unseen Docker startup failure is resolved.

## Retained installer verification timeout evidence and correction

Human Nginx logs show all new desktop/mobile assets returned 200, followed by
the retained 0.4.0 blockmap (200, 126116 bytes), then the old EXE from 05:53:25 to
05:54:25 UTC. Its retained partial output was 25280494 bytes; the matching local
original EXE is 120268755 bytes. Parent finish limits that complete download to
60 seconds. This identifies the large retained-file curl verification timeout,
not API startup, as the remaining command failure. API cleanup stopping the
container also explains the subsequent Nginx upstream `api` lookup failure.

Within this checkpoint wrapper only, finish now routes its private public-* and
retained-public-* asset curl requests to 127.0.0.1 via curl --resolve while
preserving HTTPS hostname/SNI, certificate verification, the existing Nginx
route, complete body and original SHA256 gate. No insecure TLS flag is allowed;
only the exact domain/private output pattern is intercepted. --noproxy ensures
the origin request does not go through an inherited proxy. Actual public API
health remains on normal DNS/public connectivity. Every current/retained file
still has full-body validation; no file is deleted, truncated, skipped or exempted
from preservation checks. Request paths are printed for actionable phase evidence.

Two focused tests failed for the missing origin routing, then passed. Complete
fixture bytes still release only after their original hash matches; corrupt bytes
stop without release/completion. All eight targeted startup/retry/evidence checks
passed locally; no full application suite or agent cloud execution was performed.
Final ECS success remains pending the human recovery receipt.

## Already-released final-start checkpoint

Human diagnostics at 14:16 CST confirm schema `20261005_independent_stock`,
maintenance=false, maintenance owner=null, pending resets=0. The same pinned
normal API (worker=1) started at 14:06:08, passed an actual healthcheck at
14:06:14 (exit 0), then was stopped at 14:06:25 (exit 137, OOMKilled=false).
The old driver's catch unconditionally stops API after a final command failure.
The subsequent Nginx upstream lookup errors are consistent with the stopped API.
The precise original final failing command is not available; do not claim that
the healthy normal API crashed or that an OOM caused this outage.

The stock-owned resume is no longer applicable: its lease has already been
released. `stock_final_start.py` / `invoke-stock-final-start.ps1 -Checkpoint
FinalStart -ApplyAfterPreview` support only this exact released checkpoint.
They verify original source/tool/private config hashes, installed server/page
bytes, protected references, ready/restore-required receipts, actual released
PG17 state, role/owner/schema integrity, valid audit chain, and the existing API's
exact image, normal environment and one-container identity. They start that
existing container by ID only if it is stopped; no Compose recreation, build,
source switch, DDL, reset, lease takeover, restore, stock photo import, cleanup
or installer publication is performed. Normal reset/spool startup remains active.

Nginx DNS readiness and public health after asynchronous reload are bounded
condition waits, not blind API restart retries. A failed public check retains
the running API, actual redacted command error, and private diagnostic evidence.
The restored-worker/completed receipts are written only after normal API health,
public API health, mobile download HTML, released state and preserved reference
checks pass. Identical receipts are reusable; conflicting ones are never erased.

Four focused regressions initially failed for the absent released-checkpoint
recovery and passed after implementation. Docker/PG/network executions are
external-boundary simulations, not real ECS testing. Human final execution and
`STOCK_FINAL_START_OK` remain required; neither new installers nor actual
phone/desktop login acceptance is claimed by this recovery.
