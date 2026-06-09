#!/usr/bin/env bash
# Start Celery worker(s) that run captures + NLP off the web process.
# Requires Redis running and CELERY_BROKER_URL set in .env.
#
#   ./scripts/worker.sh        # 1 worker
#   ./scripts/worker.sh 3      # 3 parallel workers (capture fans out across them)
#
# Capture is fanned out one task per provider, so to actually run providers in
# PARALLEL you need more than one worker process. Each worker uses the solo pool
# (no fork() — avoids macOS fork-safety crashes from torch / Playwright, one
# heavy capture per worker at a time), so we launch N separate solo processes
# rather than raising --concurrency.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV_PY=".venv/bin/celery"
[ -x "$VENV_PY" ] || VENV_PY="celery"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

N="${1:-1}"

if ! [[ "$N" =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: ./scripts/worker.sh [positive-integer-worker-count]" >&2
  exit 2
fi

start_worker() {  # $1 = node name suffix
  "$VENV_PY" -A backend.tasks.celery_app worker \
    --pool=solo \
    --concurrency=1 \
    --loglevel=info \
    -n "w${1}@%h"
}

if [ "$N" -le 1 ]; then
  exec start_worker 1
fi

pids=()
for i in $(seq 1 "$N"); do
  start_worker "$i" &
  pids+=("$!")
done
# Ctrl-C / TERM cleans up every child worker.
trap 'kill "${pids[@]}" 2>/dev/null || true' INT TERM EXIT
wait
