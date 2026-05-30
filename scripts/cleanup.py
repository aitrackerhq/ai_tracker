"""Manually purge artifacts older than the TTL (default: ARTIFACT_TTL_DAYS).

Usage:
    python -m scripts.cleanup            # use configured TTL
    python -m scripts.cleanup 3          # override: purge older than 3 days

Suitable for a cron entry, e.g. daily:
    0 3 * * *  cd /path/to/ai_tracker && .venv/bin/python -m scripts.cleanup
"""
import sys

from backend.storage import purge_expired

if __name__ == "__main__":
    ttl = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = purge_expired(ttl)
    print(f"purged {result['runs_purged']} runs, deleted {result['files_deleted']} files "
          f"(ttl={result['ttl_days']}d)")
