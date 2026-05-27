from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.config import settings
from backend.providers.base import BaseProvider, CaptureResult, ProviderError
from backend.utils.helpers import collapse_ws, domain_from_url, utc_now_iso

logger = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search"


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
        if not settings.serp_api_key:
            raise ProviderError(
                "SERP_API_KEY is not set. "
                "Get a free key at https://serpapi.com/manage-api-key and add it to .env"
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
            # Step 1 — normal Google search
            step1 = await self._get(
                client,
                {
                    "engine": "google",
                    "q": query,
                    "api_key": settings.serp_api_key,
                    "hl": "en",
                    "gl": "us",
                    "num": 10,
                },
            )
            ai_overview = dict(step1.get("ai_overview") or {})

            # Step 2 — if Google deferred the overview, fetch it via page_token
            page_token = ai_overview.get("page_token")
            if page_token and not ai_overview.get("text_blocks"):
                logger.info("google_ai: deferred overview, fetching via page_token")
                step2 = await self._get(
                    client,
                    {
                        "engine": "google_ai_overview",
                        "page_token": page_token,
                        "api_key": settings.serp_api_key,
                    },
                )
                ov2 = step2.get("ai_overview") or {}
                if ov2.get("text_blocks"):
                    ov2 = dict(ov2)
                    ov2["_two_step"] = True
                    return ov2, step1

            return ai_overview, step1

    async def _get(self, client: httpx.AsyncClient, params: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await client.get(SERPAPI_ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"SerpAPI request failed: {exc}") from exc
        if resp.status_code == 401:
            raise ProviderError("SerpAPI rejected the API key (401). Check SERP_API_KEY.")
        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderError(f"SerpAPI returned non-JSON (status {resp.status_code})") from exc
        if isinstance(data, dict) and data.get("error"):
            raise ProviderError(f"SerpAPI error: {data['error']}")
        return data

    # ------------------------------------------------------------------ parse

    def _extract_text(self, ai_overview: dict[str, Any]) -> str:
        blocks = ai_overview.get("text_blocks") or []
        lines = self._render_blocks(blocks)
        return "\n".join(lines).strip()

    def _render_blocks(self, blocks: list[dict[str, Any]]) -> list[str]:
        """Recursively flatten SerpAPI text_blocks into readable lines.

        Block types seen in the API: paragraph, heading, list, expandable,
        comparison. Lists carry `list` items (title + snippet) and any type can
        carry nested `text_blocks`.
        """
        out: list[str] = []
        for block in blocks:
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
                        out.extend(self._render_blocks(nested_item))
            elif snippet:
                out.append(snippet)

            # nested blocks (e.g. expandable / comparison containers)
            if btype != "list":
                nested = block.get("text_blocks")
                if nested:
                    out.extend(self._render_blocks(nested))
        return out

    def _extract_citations(self, ai_overview: dict[str, Any]) -> list[dict[str, Any]]:
        """Citations live in `references`; fall back to `sources` for older shapes."""
        citations: list[dict[str, Any]] = []
        seen: set[str] = set()
        refs = ai_overview.get("references") or ai_overview.get("sources") or []
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
