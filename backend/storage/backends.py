"""Pluggable artifact storage: local disk or Supabase Storage (S3-compatible).

A "ref" is an opaque string stored in the DB:
  - local backend:    a filesystem path (back-compat with existing data)
  - Supabase backend: "s3://<key>"  (e.g. "s3://raw/<uid>.json")

Selected automatically: Supabase when configured (settings.storage_enabled),
else local. (Legacy "r2://" refs are still recognized as remote.)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

_S3_PREFIX = "s3://"
_REMOTE_PREFIXES = ("s3://", "r2://")  # accept legacy r2:// refs as remote too
_EXT = {"raw": "json", "processed": "json", "screenshots": "png", "html": "html"}
_CONTENT_TYPE = {
    "json": "application/json",
    "png": "image/png",
    "html": "text/html; charset=utf-8",
}


class LocalBackend:
    """Artifact backend backed by the local filesystem."""
    is_local = True

    def __init__(self, base: Path):
        """Bind to a base storage directory."""
        self.base = base

    def _path(self, category: str, uid: str) -> Path:
        """Return the on-disk path for a category/uid artifact."""
        d = self.base / category
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{uid}.{_EXT.get(category, 'bin')}"

    def put_json(self, category: str, uid: str, data: dict[str, Any]) -> str:
        """Write JSON to disk; return its path ref."""
        p = self._path(category, uid)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(p)

    def put_artifact(self, category: str, uid: str, local_path: str) -> str:
        """Return the already-written local path as the ref."""
        # provider already wrote the file locally; for local backend that's the ref
        return str(local_path)

    def load_json(self, ref: str) -> dict[str, Any]:
        """Read and parse a JSON artifact from disk."""
        return json.loads(Path(ref).read_text(encoding="utf-8"))

    def read_bytes(self, ref: str) -> tuple[bytes, str] | None:
        """Read an artifact's bytes and content type, or None if missing."""
        p = Path(ref)
        if not p.exists():
            return None
        ext = p.suffix.lstrip(".")
        return p.read_bytes(), _CONTENT_TYPE.get(ext, "application/octet-stream")

    def delete(self, ref: str) -> bool:
        """Delete a local artifact; return True if removed."""
        try:
            p = Path(ref)
            if p.exists():
                p.unlink()
                return True
        except Exception:
            logger.warning("local delete failed: %s", ref)
        return False

    def url(self, ref: str) -> str | None:
        """No direct URL — local artifacts are served via the API."""
        return None  # served via the API (FileResponse)


class SupabaseBackend:
    """Supabase Storage via its S3-compatible endpoint (boto3)."""

    is_local = False

    def __init__(self):
        """Create the boto3 S3 client for Supabase Storage."""
        import boto3  # imported lazily so local installs don't need boto3
        from botocore.config import Config

        self.bucket = settings.supabase_storage_bucket
        ref = settings.supabase_project_ref
        # public object base, e.g. https://<ref>.storage.supabase.co/storage/v1/object/public/<bucket>
        self.public_base = (
            f"https://{ref}.storage.supabase.co/storage/v1/object/public/{self.bucket}"
            if (settings.supabase_storage_public and ref)
            else ""
        )
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.supabase_s3_endpoint_url,
            aws_access_key_id=settings.supabase_s3_access_key_id,
            aws_secret_access_key=settings.supabase_s3_secret_access_key,
            region_name=settings.supabase_s3_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
        # Legacy artifacts written to local disk have filesystem-path refs;
        # resolve those through the local backend instead of treating them as keys.
        self._local = LocalBackend(settings.storage_dir)

    @staticmethod
    def _is_remote(ref: str) -> bool:
        """True if the ref points at remote storage (s3:// or legacy r2://)."""
        return ref.startswith(_REMOTE_PREFIXES)

    @staticmethod
    def _key(ref: str) -> str:
        """Strip the remote prefix to get the object key."""
        for p in _REMOTE_PREFIXES:
            if ref.startswith(p):
                return ref[len(p):]
        return ref

    def put_json(self, category: str, uid: str, data: dict[str, Any]) -> str:
        """Upload JSON to the bucket; return its s3:// ref."""
        key = f"{category}/{uid}.json"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        return f"{_S3_PREFIX}{key}"

    def put_artifact(self, category: str, uid: str, local_path: str) -> str:
        """Upload a local file to the bucket; return its s3:// ref."""
        ext = _EXT.get(category, Path(local_path).suffix.lstrip(".") or "bin")
        key = f"{category}/{uid}.{ext}"
        self.client.upload_file(
            str(local_path), self.bucket, key,
            ExtraArgs={"ContentType": _CONTENT_TYPE.get(ext, "application/octet-stream")},
        )
        # local file was a temp staging copy — remove it now that it's uploaded.
        # Best-effort: a leftover temp file must not fail the (successful) upload.
        try:
            Path(local_path).unlink(missing_ok=True)
        except Exception:
            logger.debug("could not remove local staging file %s after upload",
                         local_path, exc_info=True)
        return f"{_S3_PREFIX}{key}"

    def load_json(self, ref: str) -> dict[str, Any]:
        """Fetch and parse a JSON object from the bucket (or legacy local ref)."""
        if not self._is_remote(ref):  # legacy local-path ref
            return self._local.load_json(ref)
        obj = self.client.get_object(Bucket=self.bucket, Key=self._key(ref))
        return json.loads(obj["Body"].read().decode("utf-8"))

    def read_bytes(self, ref: str) -> tuple[bytes, str] | None:
        """Fetch an object's bytes and content type, or None if missing."""
        if not self._is_remote(ref):  # legacy local-path ref
            return self._local.read_bytes(ref)
        from botocore.exceptions import ClientError

        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(ref))
            return obj["Body"].read(), obj.get("ContentType", "application/octet-stream")
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("NoSuchKey", "NotFound", "404"):
                return None  # genuinely missing → 404 at the API
            # permission/network/etc — don't masquerade as "not found"
            logger.warning("storage read failed for %s (bucket=%s): %s", ref, self.bucket, code)
            raise

    def delete(self, ref: str) -> bool:
        """Delete an object from the bucket; return True on success."""
        if not self._is_remote(ref):  # legacy local-path ref
            return self._local.delete(ref)
        from botocore.exceptions import ClientError

        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(ref))
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            logger.warning("storage delete failed: %s (code=%s)", ref, code)
            return False

    def url(self, ref: str) -> str | None:
        """Return a public or presigned URL for the object."""
        if not self._is_remote(ref):  # legacy local ref → served via the API
            return None
        key = self._key(ref)
        if self.public_base:
            return f"{self.public_base}/{key}"
        try:
            return self.client.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=3600
            )
        except Exception:
            return None


def _build_backend():
    """Select the artifact backend: Supabase when configured (fail-fast on init
    error), else local disk."""
    if settings.storage_enabled:
        try:
            b = SupabaseBackend()
            logger.info("storage backend: Supabase Storage (bucket=%s)", settings.supabase_storage_bucket)
            return b
        except Exception:
            # Fail fast: silently using local disk when remote is configured risks
            # split-brain artifact refs (new local + old remote) across instances.
            logger.exception("Supabase Storage init failed")
            raise RuntimeError("Supabase Storage is enabled but failed to initialize")
    logger.info("storage backend: local disk (%s)", settings.storage_dir)
    return LocalBackend(settings.storage_dir)


backend = _build_backend()


# ---- module-level facade (what the rest of the app calls) ----

def put_json(category: str, uid: str, data: dict[str, Any]) -> str:
    """Store JSON via the active backend."""
    return backend.put_json(category, uid, data)


def put_artifact(category: str, uid: str, local_path: str) -> str:
    """Store a file artifact via the active backend."""
    return backend.put_artifact(category, uid, local_path)


def load_json(ref: str) -> dict[str, Any]:
    """Load JSON via the active backend."""
    return backend.load_json(ref)


def read_bytes(ref: str) -> tuple[bytes, str] | None:
    """Read artifact bytes via the active backend."""
    return backend.read_bytes(ref)


def delete_ref(ref: str | None) -> bool:
    """Delete an artifact ref via the active backend."""
    if not ref:
        return False
    return backend.delete(ref)


def artifact_url(ref: str) -> str | None:
    """Return a URL for an artifact ref, if any."""
    return backend.url(ref)


def is_local() -> bool:
    """True when the active backend is local disk."""
    return backend.is_local
