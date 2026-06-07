"""Minimal async Gemini client (generativelanguage API).

Used for prompt suggestions, sentiment/framing, and competitor detection.
All calls are best-effort: callers should handle LLMUnavailable gracefully so
the core capture/processing pipeline never hard-depends on the LLM.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from backend.config import settings
from backend.utils.key_rotation import KeyRotator, parse_keys

logger = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# Rotates across GEMINI_API_KEYS (comma list) or the single GEMINI_API_KEY.
_keys = KeyRotator(parse_keys(settings.gemini_api_keys, settings.gemini_api_key))

# HTTP statuses worth trying the next key for (quota/auth), not a hard failure.
_ROTATE_STATUSES = {401, 403, 429}


class LLMUnavailable(Exception):
    pass


def is_configured() -> bool:
    return bool(_keys)


async def generate(prompt: str, *, temperature: float = 0.4, max_output_tokens: int = 2048) -> str:
    """Return the model's text. Rotates through keys on quota/auth errors."""
    if not _keys:
        raise LLMUnavailable("No Gemini API key configured")

    url = _ENDPOINT.format(model=settings.gemini_model)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens},
    }
    last_err = "unknown error"
    async with httpx.AsyncClient(timeout=60.0) as client:
        for key in _keys.ordered_from_current():
            try:
                resp = await client.post(
                    url,
                    headers={"Content-Type": "application/json", "X-goog-api-key": key},
                    json=payload,
                )
            except httpx.HTTPError as exc:
                last_err = f"request failed: {exc}"
                continue
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    raise LLMUnavailable("Gemini returned no candidates")
                parts = (candidates[0].get("content") or {}).get("parts") or []
                return "".join(
                    p.get("text", "") for p in parts if "text" in p and not p.get("thought")
                ).strip()
            if resp.status_code in _ROTATE_STATUSES:
                last_err = f"HTTP {resp.status_code}: {resp.text[:120]}"
                logger.warning("Gemini key exhausted/invalid, rotating: %s", last_err)
                _keys.advance()
                continue
            # other errors are not key-related — fail fast
            raise LLMUnavailable(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")
    raise LLMUnavailable(f"All Gemini keys failed: {last_err}")


async def generate_json(prompt: str, *, temperature: float = 0.2) -> Any:
    """Generate and parse a JSON response. Strips markdown fences. Returns parsed
    JSON (dict/list) or raises LLMUnavailable on failure."""
    raw = await generate(prompt, temperature=temperature)
    cleaned = _FENCE_RE.sub("", raw).strip()
    # Best-effort: grab the first {...} or [...] block if extra prose leaked in.
    if not cleaned.startswith(("{", "[")):
        m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"Gemini did not return valid JSON: {cleaned[:200]}") from exc
