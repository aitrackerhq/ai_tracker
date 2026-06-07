"""Pluggable artifact storage: local disk or Cloudflare R2 (S3-compatible).

A "ref" is an opaque string stored in the DB:
  - local backend: a filesystem path (back-compat with existing data)
  - R2 backend:    "r2://<key>"  (e.g. "r2://raw/<uid>.json")

Selected automatically: R2 when configured (settings.r2_enabled), else local.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

_R2_PREFIX = "r2://"
_EXT = {"raw": "json", "processed": "json", "screenshots": "png", "html": "html"}
_CONTENT_TYPE = {
    "json": "application/json",
    "png": "image/png",
    "html": "text/html; charset=utf-8",
}


class LocalBackend:
    is_local = True

    def __init__(self, base: Path):
        self.base = base

    def _path(self, category: str, uid: str) -> Path:
        d = self.base / category
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{uid}.{_EXT.get(category, 'bin')}"

    def put_json(self, category: str, uid: str, data: dict[str, Any]) -> str:
        p = self._path(category, uid)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(p)

    def put_artifact(self, category: str, uid: str, local_path: str) -> str:
        # provider already wrote the file locally; for local backend that's the ref
        return str(local_path)

    def load_json(self, ref: str) -> dict[str, Any]:
        return json.loads(Path(ref).read_text(encoding="utf-8"))

    def read_bytes(self, ref: str) -> tuple[bytes, str] | None:
        p = Path(ref)
        if not p.exists():
            return None
        ext = p.suffix.lstrip(".")
        return p.read_bytes(), _CONTENT_TYPE.get(ext, "application/octet-stream")

    def delete(self, ref: str) -> bool:
        try:
            p = Path(ref)
            if p.exists():
                p.unlink()
                return True
        except Exception:
            logger.warning("local delete failed: %s", ref)
        return False

    def url(self, ref: str) -> str | None:
        return None  # served via the API (FileResponse)


class R2Backend:
    is_local = False

    def __init__(self):
        import boto3  # imported lazily so local installs don't need boto3
        from botocore.config import Config

        endpoint = settings.r2_endpoint_url or (
            f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
        )
        self.bucket = settings.r2_bucket
        self.public_base = settings.r2_public_base_url.rstrip("/") if settings.r2_public_base_url else ""
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
        # Legacy artifacts written before R2 was enabled have local-path refs;
        # resolve those through the local backend instead of treating them as keys.
        self._local = LocalBackend(settings.storage_dir)

    @staticmethod
    def _is_r2(ref: str) -> bool:
        return ref.startswith(_R2_PREFIX)

    @staticmethod
    def _key(ref: str) -> str:
        return ref[len(_R2_PREFIX):] if ref.startswith(_R2_PREFIX) else ref

    def put_json(self, category: str, uid: str, data: dict[str, Any]) -> str:
        key = f"{category}/{uid}.json"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        return f"{_R2_PREFIX}{key}"

    def put_artifact(self, category: str, uid: str, local_path: str) -> str:
        ext = _EXT.get(category, Path(local_path).suffix.lstrip(".") or "bin")
        key = f"{category}/{uid}.{ext}"
        self.client.upload_file(
            str(local_path), self.bucket, key,
            ExtraArgs={"ContentType": _CONTENT_TYPE.get(ext, "application/octet-stream")},
        )
        # local file was a temp staging copy — remove it now that it's in R2.
        # Best-effort: a leftover temp file must not fail the (successful) upload.
        try:
            Path(local_path).unlink(missing_ok=True)
        except Exception:
            logger.debug("could not remove local staging file %s after R2 upload",
                         local_path, exc_info=True)
        return f"{_R2_PREFIX}{key}"

    def load_json(self, ref: str) -> dict[str, Any]:
        if not self._is_r2(ref):  # legacy local-path ref
            return self._local.load_json(ref)
        obj = self.client.get_object(Bucket=self.bucket, Key=self._key(ref))
        return json.loads(obj["Body"].read().decode("utf-8"))

    def read_bytes(self, ref: str) -> tuple[bytes, str] | None:
        if not self._is_r2(ref):  # legacy local-path ref
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
            logger.warning("R2 read failed for %s (bucket=%s): %s", ref, self.bucket, code)
            raise

    def delete(self, ref: str) -> bool:
        if not self._is_r2(ref):  # legacy local-path ref
            return self._local.delete(ref)
        from botocore.exceptions import ClientError

        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(ref))
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            logger.warning("r2 delete failed: %s (code=%s)", ref, code)
            return False

    def url(self, ref: str) -> str | None:
        if not self._is_r2(ref):  # legacy local ref → served via the API
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
    if settings.r2_enabled:
        try:
            b = R2Backend()
            logger.info("storage backend: Cloudflare R2 (bucket=%s)", settings.r2_bucket)
            return b
        except Exception:
            logger.exception("R2 init failed; falling back to local storage")
    logger.info("storage backend: local disk (%s)", settings.storage_dir)
    return LocalBackend(settings.storage_dir)


backend = _build_backend()


# ---- module-level facade (what the rest of the app calls) ----

def put_json(category: str, uid: str, data: dict[str, Any]) -> str:
    return backend.put_json(category, uid, data)


def put_artifact(category: str, uid: str, local_path: str) -> str:
    return backend.put_artifact(category, uid, local_path)


def load_json(ref: str) -> dict[str, Any]:
    return backend.load_json(ref)


def read_bytes(ref: str) -> tuple[bytes, str] | None:
    return backend.read_bytes(ref)


def delete_ref(ref: str | None) -> bool:
    if not ref:
        return False
    return backend.delete(ref)


def artifact_url(ref: str) -> str | None:
    return backend.url(ref)


def is_local() -> bool:
    return backend.is_local
