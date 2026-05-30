from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote_plus

from backend.config import settings
from backend.providers.base import BaseProvider
from backend.providers.stealth import wait_for_cloudflare
from backend.utils.helpers import collapse_ws, domain_from_url

logger = logging.getLogger(__name__)


class PerplexityProvider(BaseProvider):
    """Anonymous (no-login) Perplexity capture.

    perplexity.ai answers signed-out queries. Citations are first-class
    (numbered source cards), so this is a strong citation signal. Cloudflare is
    handled by the shared stealth layer.
    """

    name = "perplexity"
    url = "https://www.perplexity.ai/"

    INPUT_SELECTORS = [
        "textarea[placeholder*='Ask' i]",
        "textarea[autofocus]",
        "div[contenteditable='true']",
        "textarea",
    ]
    SUBMIT_SELECTORS = [
        "button[aria-label*='Submit' i]",
        "button[data-testid='submit-button']",
    ]
    ANSWER_SELECTORS = [
        "div[class*='prose']",
        "div[dir='auto'] .prose",
        "div[id^='markdown-content']",
        "main div[dir='auto']",
    ]
    # 'Sources' / citation anchors live in the answer area
    DISMISS_SELECTORS = [
        "button:has-text('Accept')",
        "button:has-text('Got it')",
        "button[aria-label*='Close' i]",
        "button:has-text('Continue')",
    ]

    async def initialize(self) -> None:
        await super().initialize()
        assert self.page is not None
        # Mirror the manual incognito flow: open the home page, dismiss any
        # consent/intro overlay, and wait for the composer to be ready.
        await self.page.goto(self.url, wait_until="domcontentloaded")
        # CF wait is best-effort (the detector can false-negative on the SPA);
        # we never hard-fail here — answer extraction is the real signal.
        cleared = await wait_for_cloudflare(self.page, timeout=30.0)
        if not cleared:
            logger.warning("perplexity: Cloudflare may still be active; continuing anyway")
        await self._dismiss_modals()
        # Wait for the composer to appear (anonymous chat is allowed).
        try:
            await self.page.wait_for_selector(", ".join(self.INPUT_SELECTORS), timeout=20_000)
        except Exception:
            logger.warning("perplexity: composer not found yet; will retry on send")

    async def send_prompt(self, prompt: str) -> None:
        """Type into the composer and submit — exactly like a signed-out user."""
        assert self.page is not None
        await self._dismiss_modals()
        el, sel = await self._find_first(self.INPUT_SELECTORS, timeout=15_000)
        if not el:
            # Last resort: the direct search URL.
            await self.page.goto(
                f"https://www.perplexity.ai/search?q={quote_plus(prompt)}",
                wait_until="domcontentloaded",
            )
            await self._dismiss_modals()
            return
        await el.click()
        if sel and sel.startswith("textarea"):
            await el.fill(prompt)
        else:
            await self.page.keyboard.type(prompt, delay=15)
        await asyncio.sleep(0.3)
        submit_el, _ = await self._find_first(self.SUBMIT_SELECTORS, timeout=3000)
        if submit_el:
            await submit_el.click()
        else:
            await self.page.keyboard.press("Enter")

    async def _dismiss_modals(self) -> None:
        assert self.page is not None
        for _ in range(3):
            dismissed = False
            for sel in self.DISMISS_SELECTORS:
                try:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await asyncio.sleep(0.3)
                        dismissed = True
                        break
                except Exception:
                    continue
            if not dismissed:
                return

    async def _find_first(self, selectors: list[str], timeout: int = 5000):
        assert self.page is not None
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=timeout, state="visible")
                if el:
                    return el, sel
            except Exception:
                continue
        return None, None

    async def wait_for_completion(self) -> None:
        """Text-stability detection (selector-independent)."""
        assert self.page is not None
        await asyncio.sleep(2.5)
        prev = ""
        stable = 0
        deadline = asyncio.get_event_loop().time() + settings.provider_timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            cur = await self._read_answer()
            if cur and cur == prev:
                stable += 1
                if stable >= 4:  # ~2s steady
                    break
            else:
                stable = 0
                prev = cur
            await asyncio.sleep(0.5)
        await asyncio.sleep(settings.stream_settle_seconds)

    async def _read_answer(self) -> str:
        assert self.page is not None
        for sel in self.ANSWER_SELECTORS:
            try:
                nodes = await self.page.query_selector_all(sel)
                if nodes:
                    return collapse_ws(await nodes[-1].inner_text() or "")
            except Exception:
                continue
        return ""

    async def extract_response(self) -> str:
        return await self._read_answer()

    async def extract_citations(self) -> list[dict[str, Any]]:
        assert self.page is not None
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            anchors = await self.page.query_selector_all("a[href^='http']")
            for a in anchors:
                href = await a.get_attribute("href") or ""
                d = domain_from_url(href)
                if not d or "perplexity.ai" in d or href in seen:
                    continue
                seen.add(href)
                title = collapse_ws(await a.inner_text() or "")
                results.append({"title": title[:200], "url": href, "domain": d})
        except Exception:
            pass
        return results
