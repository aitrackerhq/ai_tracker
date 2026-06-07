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
from backend.utils.helpers import domain_from_url, utc_now_iso

logger = logging.getLogger(__name__)


class GoogleAIOverviewProvider(BaseProvider):
    """Google AI Overview via SerpAPI — no browser needed.

    Implements SerpAPI's documented two-step flow:
      1. `engine=google` — a normal search. If an AI Overview is present, the
         response's `ai_overview` block either contains the full `text_blocks`
         OR just a short-lived `page_token` (Google sometimes defers it).
      2. If only a `page_token` is returned, immediately re-request with
         `engine=google_ai_overview&page_token=...` to fetch the full overview.
         The token expires in ~1 minute, so we do it back-to-back.

    Citations come from `ai_overview.references` (title/link/snippet/source).

    Set SERP_API_KEY in .env (free tier: 250 searches/month at serpapi.com).
    needs_browser = False tells the orchestrator to skip launching a browser.
    """

    needs_browser = False
    name = "google_ai"

    async def initialize(self) -> None:
        if not is_configured():
            raise ProviderError(
                "No SERP API key configured. Set SERP_API_KEY or SERP_API_KEYS in .env "
                "(https://serpapi.com/manage-api-key)."
            )

    async def capture(self, prompt: str, run_id: str) -> CaptureResult:
        started = asyncio.get_event_loop().time()
        ai_overview, raw = await self._fetch(prompt)
        elapsed = round(asyncio.get_event_loop().time() - started, 2)

        has_overview = bool(ai_overview.get("text_blocks"))
        overview_text = self._extract_text(ai_overview)
        citations = self._extract_citations(ai_overview)
        links = self._extract_organic_links(raw)

        logger.info(
            "google_ai: prompt=%r has_overview=%s citations=%d chars=%d",
            prompt,
            has_overview,
            len(citations),
            len(overview_text),
        )

        return CaptureResult(
            provider=self.name,
            prompt=prompt,
            timestamp=utc_now_iso(),
            response_text=overview_text,
            citations=citations,
            links=links,
            metadata={
                "response_time": elapsed,
                "has_citations": bool(citations),
                "search_information": raw.get("search_information") or {},
                "two_step": ai_overview.get("_two_step", False),
            },
            screenshot_path=None,  # API-based: no screenshot
            html_path=None,
            has_ai_overview=has_overview,
        )

    # ------------------------------------------------------------------ fetch

    async def _fetch(self, query: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run the two-step SerpAPI flow. Returns (ai_overview, full_search_json)."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Step 1 — normal Google search (key injected + rotated by serpapi_get)
            params: dict[str, Any] = {
                "engine": "google",
                "q": query,
                "hl": "en",
                "gl": "us",
                "num": 10,
            }
            if self.geo_location:
                params["location"] = self.geo_location
            try:
                step1 = await serpapi_get(client, params)
            except SerpAPIError as exc:
                raise ProviderError(str(exc)) from exc
            ai_overview = dict(step1.get("ai_overview") or {})

            # Step 2 — if Google deferred the overview, fetch it via page_token
            page_token = ai_overview.get("page_token")
            if page_token and not ai_overview.get("text_blocks"):
                logger.info("google_ai: deferred overview, fetching via page_token")
                try:
                    step2 = await serpapi_get(
                        client,
                        {"engine": "google_ai_overview", "page_token": page_token},
                    )
                except SerpAPIError as exc:
                    raise ProviderError(str(exc)) from exc
                ov2 = step2.get("ai_overview") or {}
                if ov2.get("text_blocks"):
                    ov2 = dict(ov2)
                    ov2["_two_step"] = True
                    return ov2, step1

            return ai_overview, step1

    # ------------------------------------------------------------------ parse

    def _extract_text(self, ai_overview: dict[str, Any]) -> str:
        return flatten_text_blocks(ai_overview.get("text_blocks") or [])

    def _extract_citations(self, ai_overview: dict[str, Any]) -> list[dict[str, Any]]:
        return extract_references(ai_overview)

    def _extract_organic_links(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in (raw.get("organic_results") or [])[:10]:
            url = result.get("link") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            links.append(
                {
                    "url": url,
                    "domain": domain_from_url(url),
                    "text": result.get("title") or "",
                    "snippet": result.get("snippet") or "",
                }
            )
        return links

    # ------------------------------------------------------------------ no-op browser hooks

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
