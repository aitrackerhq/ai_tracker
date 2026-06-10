"""
Supabase JWT authentication for FastAPI.

Validates the Bearer token issued by Supabase Auth on every protected request
and exposes the authenticated user as a FastAPI dependency (AuthDep).

Supabase projects using JWT Signing Keys issue ES256 tokens verified via JWKS.
Supabase JWTs are validated using the project's JWKS endpoint (ES256).

Required environment variables:
    SUPABASE_URL       — e.g. https://<project-ref>.supabase.co
    SUPABASE_JWT_SECRET — still used as fallback if JWKS fetch fails at startup
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from backend.config import settings

_log = logging.getLogger(__name__)

# auto_error=False so we return a clean 401 instead of FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)

_ALGORITHM = "ES256"


# ---------------------------------------------------------------------------
# Load the EC public key from Supabase's JWKS endpoint at startup.
# This is a single blocking HTTP call made once when the module is imported.
# ---------------------------------------------------------------------------

def _load_jwks() -> list[dict]:
    """
    Fetch the JSON Web Key Set from Supabase.

    Returns the list of JWK dicts that python-jose accepts directly as
    the 'key' argument to jwt.decode() when algorithms=["ES256"].
    Raises RuntimeError if the fetch fails so the app won't start silently broken.
    """
    if not settings.supabase_url:
        raise RuntimeError(
            "SUPABASE_URL is not set.\n"
            "Set it to your Supabase project URL, e.g. https://<ref>.supabase.co"
        )
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        keys = resp.json().get("keys", [])
        if not keys:
            raise RuntimeError(f"JWKS endpoint returned no keys: {url}")
        _log.info("Loaded %d key(s) from Supabase JWKS", len(keys))
        return keys
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Failed to fetch Supabase JWKS from {url}: {exc}") from exc


_JWKS: list[dict] = _load_jwks()


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CurrentUser:
    """Authenticated user extracted from a validated Supabase JWT."""

    id: str    # Supabase user UUID (`sub` claim)
    email: str # User email (`email` claim)


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """
    Validate the Supabase JWT from the Authorization header and return the caller.

    Verifies signature (ES256 via JWKS), expiry, and audience ("authenticated").
    Raises HTTP 401 for missing, expired, or invalid tokens.
    """
    _401 = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise _401

    try:
        payload = jwt.decode(
            credentials.credentials,
            _JWKS,                       # python-jose accepts a JWKS key list directly
            algorithms=[_ALGORITHM],
            audience="authenticated",
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except JWTError as exc:
        _log.debug("JWT validation failed: %s", exc)
        raise _401 from None

    user_id: str | None = payload.get("sub")
    email: str | None   = payload.get("email")

    if not user_id or not email:
        raise _401

    return CurrentUser(id=user_id, email=email)


# Annotated dependency alias — use this in route signatures:
#   def my_route(current_user: AuthDep): ...
AuthDep = Annotated[CurrentUser, Depends(get_current_user)]