#!/usr/bin/env bash
# Start a Celery worker that runs captures + NLP off the web process.
# Requires Redis running and CELERY_BROKER_URL set in .env.
#
#   ./scripts/worker.sh
#
# Uses the solo pool: no fork() — avoids macOS fork-safety crashes from
# torch / Playwright, and keeps one heavy capture per worker at a time.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV_PY=".venv/bin/celery"
[ -x "$VENV_PY" ] || VENV_PY="celery"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
exec "$VENV_PY" -A backend.tasks.celery_app worker \
  --pool=solo \
  --concurrency=1 \
  --loglevel=info
