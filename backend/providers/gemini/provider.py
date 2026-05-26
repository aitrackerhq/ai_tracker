from __future__ import annotations

import asyncio
from typing import Any

from backend.config import settings
from backend.providers.base import BaseProvider, ProviderError
from backend.providers.stealth import wait_for_cloudflare
from backend.utils.helpers import collapse_ws, domain_from_url


class GeminiProvider(BaseProvider):
    """Anonymous (no-login) Gemini capture.

    gemini.google.com lets signed-out visitors run prompts. The hurdles are the
    consent dialog and the occasional "Sign in for more" prompts — none of which
    block the input box.
    """

    name = "gemini"
    url = "https://gemini.google.com/app"

    INPUT_SELECTORS = [
        "div.ql-editor[contenteditable='true']",
        "rich-textarea div[contenteditable='true']",
        "div[contenteditable='true'][role='textbox']",
        "textarea[aria-label*='Enter a prompt' i]",
        "textarea[aria-label*='prompt' i]",
    ]
    SEND_BUTTON_SELECTORS = [
        "button[aria-label*='Send message' i]",
        "button[aria-label*='Send' i]",
        "button.send-button",
    ]
    RESPONSE_SELECTORS = [
        "model-response message-content",
        "message-content.model-response-text",
        ".markdown.markdown-main-panel",
        "[data-test-id='response-content']",
    ]
    GENERATING_INDICATOR = [
        "div.response-container.is-thinking",
        ".stop-generating-button",
        "button[aria-label*='Stop' i]",
        "mat-progress-bar:not([style*='display: none'])",
    ]
    # Consent + "sign in for more" prompts that may appear but don't block input
    DISMISS_SELECTORS = [
        "button:has-text('Accept all')",
        "button:has-text('I agree')",
        "button:has-text('Reject all')",
        "button[aria-label*='Accept all' i]",
        "button:has-text('No thanks')",
        "button:has-text('Got it')",
        "button:has-text('Continue')",
        "button[aria-label*='Close' i]",
    ]

    async def initialize(self) -> None:
        await super().initialize()
        assert self.page is not None
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await wait_for_cloudflare(self.page, timeout=20.0)
        await self._dismiss_modals()
        try:
            await self.page.wait_for_selector(
                ", ".join(self.INPUT_SELECTORS),
                timeout=25_000,
            )
        except Exception as exc:
            # Gemini has regional restrictions — if the input never appears
            # there's likely a geo/age block, not an auth one.
            raise ProviderError(
                "Gemini input box not found. Possible causes: regional restriction, "
                "consent dialog variant we don't handle, or DOM change. Check the "
                "saved screenshot/html artifacts under storage/."
            ) from exc

    async def _dismiss_modals(self) -> None:
        """Iterate a few times in case multiple overlays stack (cookie banner + intro tour)."""
        assert self.page is not None
        for _ in range(4):
            dismissed = False
            for sel in self.DISMISS_SELECTORS:
                try:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await asyncio.sleep(0.4)
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

    async def send_prompt(self, prompt: str) -> None:
        assert self.page is not None
        await self._dismiss_modals()
        el, sel = await self._find_first(self.INPUT_SELECTORS, timeout=10_000)
        if not el:
            raise ProviderError("Gemini input not found")
        await el.click()
        if sel and sel.startswith("textarea"):
            await el.fill(prompt)
        else:
            await self.page.keyboard.type(prompt, delay=15)
        send_el, _ = await self._find_first(self.SEND_BUTTON_SELECTORS, timeout=5000)
        if send_el:
            await send_el.click()
        else:
            await self.page.keyboard.press("Enter")

    async def wait_for_completion(self) -> None:
        assert self.page is not None
        # Wait for a response container to appear
        try:
            await self.page.wait_for_selector(", ".join(self.RESPONSE_SELECTORS), timeout=30_000)
        except Exception:
            pass
        # Wait until generating indicator disappears
        deadline = asyncio.get_event_loop().time() + settings.provider_timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            generating = False
            for sel in self.GENERATING_INDICATOR:
                try:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        generating = True
                        break
                except Exception:
                    continue
            if not generating:
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(settings.stream_settle_seconds)

    async def extract_response(self) -> str:
        assert self.page is not None
        for sel in self.RESPONSE_SELECTORS:
            try:
                nodes = await self.page.query_selector_all(sel)
                if nodes:
                    text = await nodes[-1].inner_text()
                    return collapse_ws(text)
            except Exception:
                continue
        return ""

    async def extract_citations(self) -> list[dict[str, Any]]:
        assert self.page is not None
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for sel in self.RESPONSE_SELECTORS:
            try:
                nodes = await self.page.query_selector_all(sel)
                if not nodes:
                    continue
                anchors = await nodes[-1].query_selector_all("a[href]")
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    if not href.startswith("http"):
                        continue
                    d = domain_from_url(href)
                    if not d or href in seen:
                        continue
                    seen.add(href)
                    title = collapse_ws(await a.inner_text() or "")
                    results.append({"title": title[:200], "url": href, "domain": d})
                if results:
                    break
            except Exception:
                continue
        return results
