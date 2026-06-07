"""Shared SerpAPI helpers: key rotation, request, and parsing for responses that
carry `text_blocks` + `references` (Google AI Overview and Google AI Mode)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.config import settings
from backend.utils.helpers import collapse_ws, domain_from_url
from backend.utils.key_rotation import KeyRotator, parse_keys

logger = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search"

# Rotates across SERP_API_KEYS (comma list) or the single SERP_API_KEY.
serp_keys = KeyRotator(parse_keys(settings.serp_api_keys, settings.serp_api_key))

# error-text fragments that mean "this key is out of quota" → try the next one
_QUOTA_HINTS = ("run out of searches", "ran out of searches", "exceeded", "plan limit",
                "out of searches", "account has no searches")

# HTTP statuses that warrant rotating to the next key (auth/quota/rate-limit)
_ROTATE_STATUSES = {401, 403, 429}


class SerpAPIError(Exception):
    pass


def is_configured() -> bool:
    return bool(serp_keys)


async def serpapi_get(client: httpx.AsyncClient, params: dict[str, Any]) -> dict[str, Any]:
    """GET SerpAPI, injecting + rotating the api_key on quota/auth failures."""
    if not serp_keys:
        raise SerpAPIError("No SERP API key configured (set SERP_API_KEY or SERP_API_KEYS)")
    last_err = "unknown error"
    for key in serp_keys.ordered_from_current():
        q = {**params, "api_key": key}
        try:
            resp = await client.get(SERPAPI_ENDPOINT, params=q)
        except httpx.HTTPError as exc:
            last_err = f"request failed: {exc}"
            continue
        if resp.status_code in _ROTATE_STATUSES:
            last_err = f"HTTP {resp.status_code} (auth/quota)"
            logger.warning("SerpAPI key failed (HTTP %d), rotating", resp.status_code)
            serp_keys.advance()
            continue
        try:
            data = resp.json()
        except Exception as exc:
            raise SerpAPIError(
                f"SerpAPI returned non-JSON (status {resp.status_code})"
            ) from exc
        err = (data.get("error") or "") if isinstance(data, dict) else ""
        if err and any(h in err.lower() for h in _QUOTA_HINTS):
            last_err = err
            logger.warning("SerpAPI key out of quota, rotating: %s", err)
            serp_keys.advance()
            continue
        if err:
            raise SerpAPIError(f"SerpAPI error: {err}")
        return data
    raise SerpAPIError(f"All SERP API keys failed: {last_err}")


def flatten_text_blocks(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(_render(blocks)).strip()


def _render(blocks: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for block in blocks or []:
        btype = block.get("type", "")
        snippet = collapse_ws(block.get("snippet") or "")
        if btype == "list":
            for item in block.get("list") or []:
                title = collapse_ws(item.get("title") or "")
                isnip = collapse_ws(item.get("snippet") or "")
                line = ": ".join(x for x in (title, isnip) if x)
                if line:
                    out.append(f"• {line}")
                nested_item = item.get("text_blocks")
                if nested_item:
                    out.extend(_render(nested_item))
        elif snippet:
            out.append(snippet)
        if btype != "list":
            nested = block.get("text_blocks")
            if nested:
                out.extend(_render(nested))
    return out


def extract_references(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Citations live in `references`; fall back to `sources` for older shapes."""
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    refs = container.get("references") or container.get("sources") or []
    for ref in refs:
        url = ref.get("link") or ref.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        citations.append(
            {
                "title": ref.get("title") or "",
                "url": url,
                "domain": domain_from_url(url),
                "source": ref.get("source") or "",
            }
        )
    return citations
