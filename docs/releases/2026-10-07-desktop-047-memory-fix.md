# 0.4.7 deployment RAM ordering fix

Observed: offline image built successfully, then the 768 MiB restore gate
measured 758 MiB while the old API was still running. No maintenance claim or
schema migration had happened in this failed job.

The deployment now checks the 512 MiB one-shot budget while the API runs, stops
API writes, and only then measures the unchanged 768 MiB restore budget. If
that second gate fails, it verifies the old schema, absence of maintenance and
pending resets, plus exact original container ID/image/config before restarting
that original API. This recovery is limited to the pre-claim phase; it does not
restore a database, clear any maintenance, or start old code on a migrated schema.

Regression checks cover the real deploy() ordering with 758 MiB live, sufficient
RAM after stopping the API, shortage after stopping, and rejection of a changed
container image. Resource limits and all backup/restore/row-integrity checks stay
unchanged.

Repackage committed SOURCE/WEB and refresh delivery metadata. Keep existing
0.4.7 installers byte-for-byte and retain the previous ZIP and failed cloud job.
Run the refreshed 01-部署云端.ps1 in all mode as a fresh preflight/deploy; this
pre-write failure has no ready checkpoint and must not use ready-only resume.
Cloud deployment and real-device acceptance remain human-run and unverified.
