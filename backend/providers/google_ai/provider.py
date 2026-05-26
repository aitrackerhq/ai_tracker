from __future__ import annotations

import asyncio
from typing import Any

from backend.config import settings
from backend.providers.base import BaseProvider, CaptureResult, ProviderError
from backend.utils.helpers import collapse_ws, domain_from_url, utc_now_iso


class GoogleAIOverviewProvider(BaseProvider):
    """Google AI Overview via SerpAPI — no browser needed.

    Uses the SerpAPI /search endpoint which returns a structured `ai_overview`
    block (text + cited sources) — exactly what users see in Google Search.
    Set SERP_API_KEY in .env (free tier: 250 searches/month at serpapi.com).

    needs_browser = False tells the orchestrator to skip launching a browser
    context for this provider entirely.
    """

    needs_browser = False

    name = "google_ai"

    async def initialize(self) -> None:
        # No browser required; skip parent's page creation entirely.
        if not settings.serp_api_key:
            raise ProviderError(
                "SERP_API_KEY is not set. "
                "Get a free key at https://serpapi.com/manage-api-key and add it to .env"
            )

    async def capture(self, prompt: str, run_id: str) -> CaptureResult:
        started = asyncio.get_event_loop().time()
        raw = await asyncio.to_thread(self._fetch_serpapi, prompt)
        elapsed = round(asyncio.get_event_loop().time() - started, 2)

        ai_overview = raw.get("ai_overview") or {}
        has_overview = bool(ai_overview)

        overview_text = self._extract_text(ai_overview)
        citations = self._extract_citations(ai_overview)
        links = self._extract_organic_links(raw)

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
            },
            screenshot_path=None,  # API-based: no screenshot
            html_path=None,
            has_ai_overview=has_overview,
        )

    # ------------------------------------------------------------------ helpers

    def _fetch_serpapi(self, query: str) -> dict[str, Any]:
        """Synchronous SerpAPI call — wrapped in asyncio.to_thread by caller."""
        try:
            from serpapi import GoogleSearch  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderError(
                "serpapi package not installed. Run: pip install google-search-results"
            ) from exc

        search = GoogleSearch(
            {
                "engine": "google",
                "q": query,
                "api_key": settings.serp_api_key,
                "hl": "en",
                "gl": "us",
                "num": 10,
            }
        )
        return search.get_dict()

    def _extract_text(self, ai_overview: dict[str, Any]) -> str:
        """Flatten text_blocks into a single readable string."""
        if not ai_overview:
            return ""
        parts: list[str] = []
        for block in ai_overview.get("text_blocks") or []:
            btype = block.get("type", "")
            if btype == "paragraph":
                snippet = block.get("snippet") or ""
                if snippet:
                    parts.append(collapse_ws(snippet))
            elif btype == "list":
                for item in block.get("list") or []:
                    snippet = item.get("snippet") or ""
                    if snippet:
                        parts.append(f"• {collapse_ws(snippet)}")
            else:
                # fallback: grab any "snippet" key present
                snippet = block.get("snippet") or ""
                if snippet:
                    parts.append(collapse_ws(snippet))
        return "\n".join(parts)

    def _extract_citations(self, ai_overview: dict[str, Any]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in ai_overview.get("sources") or []:
            url = source.get("link") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append(
                {
                    "title": source.get("title") or "",
                    "url": url,
                    "domain": domain_from_url(url),
                }
            )
        return citations

    def _extract_organic_links(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        """Also pull top organic results as supplementary links."""
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

    # These are no-ops for an API-based provider
    async def send_prompt(self, prompt: str) -> None:
        pass

    async def wait_for_completion(self) -> None:
        pass

    async def extract_response(self) -> str:
        return ""

    async def save_artifacts(self, run_id: str):
        return None, None

    async def close(self) -> None:
        pass  # no page or context to close
