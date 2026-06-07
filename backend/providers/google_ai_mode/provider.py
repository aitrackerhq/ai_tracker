from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.providers.base import BaseProvider, CaptureResult, ProviderError
from backend.providers.serpapi_common import (
    SerpAPIError,
    extract_references,
    flatten_text_blocks,
    is_configured,
    serpapi_get,
)
from backend.utils.helpers import utc_now_iso

logger = logging.getLogger(__name__)


class GoogleAIModeProvider(BaseProvider):
    """Google AI Mode via SerpAPI (engine=google_ai_mode) — no browser needed.

    Single request; the response carries top-level `text_blocks` +
    `references` (same shape as AI Overview). Set SERP_API_KEY(S) in .env.
    """

    needs_browser = False
    name = "google_ai_mode"

    async def initialize(self) -> None:
        if not is_configured():
            raise ProviderError(
                "No SERP API key configured. Set SERP_API_KEY or SERP_API_KEYS in .env."
            )

    async def capture(self, prompt: str, run_id: str) -> CaptureResult:
        started = asyncio.get_event_loop().time()
        params: dict[str, Any] = {"engine": "google_ai_mode", "q": prompt}
        if self.geo_location:
            params["location"] = self.geo_location

        async with httpx.AsyncClient(timeout=90.0) as client:
            try:
                data = await serpapi_get(client, params)
            except SerpAPIError as exc:
                raise ProviderError(str(exc)) from exc

        elapsed = round(asyncio.get_event_loop().time() - started, 2)
        text = flatten_text_blocks(data.get("text_blocks") or [])
        citations = extract_references(data)
        has_answer = bool(text)

        logger.info(
            "google_ai_mode: prompt=%r answer=%s citations=%d chars=%d",
            prompt,
            has_answer,
            len(citations),
            len(text),
        )

        return CaptureResult(
            provider=self.name,
            prompt=prompt,
            timestamp=utc_now_iso(),
            response_text=text,
            citations=citations,
            links=[],
            metadata={
                "response_time": elapsed,
                "has_citations": bool(citations),
                "search_metadata": data.get("search_metadata") or {},
            },
            screenshot_path=None,
            html_path=None,
            has_ai_overview=has_answer,
        )

    # no-op browser hooks
    async def send_prompt(self, prompt: str) -> None:
        pass

    async def wait_for_completion(self) -> None:
        pass

    async def extract_response(self) -> str:
        return ""

    async def save_artifacts(self, run_id: str):
        return None, None

    async def close(self) -> None:
        pass
