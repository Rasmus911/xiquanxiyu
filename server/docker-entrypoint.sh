#!/usr/bin/env sh
set -eu

# Access-policy socket invalidation supports exactly one API worker/replica.
# create_app rejects API_WORKERS/WEB_CONCURRENCY/API_REPLICAS values other than 1.
# Do not run extra manually started API processes or override a process manager's
# worker count. CLI maintenance is separate; it must use the schema-owner role.
# Never activate a policy, reset business data, or infer UUID bindings here.
if [ "${RUN_MIGRATIONS:-0}" != "0" ] || [ "${SEED_DEFAULTS:-0}" != "0" ]; then
  echo "[xiquan] Normal startup forbids migration/seed flags; use explicit maintenance CLI." >&2
  exit 1
fi
# The normal image entrypoint cannot become an arbitrary maintenance command.
if [ "$#" -ne 2 ] || [ "$1" != "python" ] || [ "$2" != "run.py" ]; then
  echo "[xiquan] Normal startup requires python run.py; maintenance has a separate entrypoint." >&2
  exit 1
fi
python /app/app/deployment_checks.py
echo "[xiquan] Starting one API process. Policy activation remains manual."
exec python run.py

