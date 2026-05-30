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

logger = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMUnavailable(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.gemini_api_key)


async def generate(prompt: str, *, temperature: float = 0.4, max_output_tokens: int = 2048) -> str:
    """Return the concatenated text of the model's response."""
    if not settings.gemini_api_key:
        raise LLMUnavailable("GEMINI_API_KEY is not set")

    url = _ENDPOINT.format(model=settings.gemini_model)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": settings.gemini_api_key,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Gemini request failed: {exc}") from exc

    if resp.status_code != 200:
        raise LLMUnavailable(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMUnavailable("Gemini returned no candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    # Skip 'thought' parts; concatenate text parts.
    text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
    return text.strip()


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
