"""Smoke-test the Supabase Storage bucket.

Verifies the S3 credentials in `.env` actually reach the configured bucket by
doing a full round-trip: head bucket → put a tiny object → read it back →
delete it. Prints a per-step PASS/FAIL and exits non-zero on any failure.

    python -m scripts.check_storage

If the Supabase vars are unset the app would run in local-disk mode, so this
reports that and exits 0 (nothing to check).
"""
from __future__ import annotations

import sys

from backend.config import settings


def main() -> int:
    if not settings.storage_enabled:
        missing = [
            name
            for name, val in (
                ("SUPABASE_S3_ACCESS_KEY_ID", settings.supabase_s3_access_key_id),
                ("SUPABASE_S3_SECRET_ACCESS_KEY", settings.supabase_s3_secret_access_key),
                ("SUPABASE_STORAGE_BUCKET", settings.supabase_storage_bucket),
                ("SUPABASE_S3_REGION", settings.supabase_s3_region),
                ("SUPABASE_S3_ENDPOINT (or SUPABASE_PROJECT_REF)", settings.supabase_s3_endpoint_url),
            )
            if not val
        ]
        print("Supabase Storage not configured — app runs in local-disk mode.")
        print("  missing: " + ", ".join(missing))
        return 0

    from backend.storage.backends import SupabaseBackend

    bucket = settings.supabase_storage_bucket
    print(f"endpoint : {settings.supabase_s3_endpoint_url}")
    print(f"bucket   : {bucket}")
    print(f"region   : {settings.supabase_s3_region}")
    print("-" * 48)

    try:
        be = SupabaseBackend()
    except Exception as exc:  # noqa: BLE001 — surface init failure verbatim
        print(f"FAIL  init backend: {exc}")
        return 1

    uid = "__smoke_test__"
    ref = None
    ok = True

    # 1. head bucket — credentials + bucket exist + reachable
    try:
        be.client.head_bucket(Bucket=bucket)
        print("PASS  head bucket")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  head bucket: {exc}")
        return 1  # nothing else will work

    # 2. write
    try:
        ref = be.put_json("processed", uid, {"smoke": True})
        print(f"PASS  put object  ({ref})")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  put object: {exc}")
        return 1

    # 3. read back
    try:
        data = be.load_json(ref)
        assert data.get("smoke") is True, f"unexpected payload: {data!r}"
        print("PASS  read object")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  read object: {exc}")
        ok = False

    # 4. delete (always attempt cleanup)
    try:
        if be.delete(ref):
            print("PASS  delete object")
        else:
            print("FAIL  delete object: backend returned False")
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  delete object: {exc}")
        ok = False

    print("-" * 48)
    print("OK: Supabase Storage round-trip succeeded." if ok else "FAILED: see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
