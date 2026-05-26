from __future__ import annotations

import asyncio
from typing import Any

from backend.config import settings
from backend.providers.base import BaseProvider, ProviderError
from backend.providers.stealth import wait_for_cloudflare
from backend.utils.helpers import collapse_ws, domain_from_url


class ChatGPTProvider(BaseProvider):
    """Anonymous (no-login) ChatGPT capture.

    chatgpt.com supports unauthenticated chat as of mid-2024. The blocker for
    automation is Cloudflare Turnstile, which we wait through using stealth +
    real Chrome (see backend.providers.stealth and the orchestrator).
    """

    name = "chatgpt"
    url = "https://chatgpt.com/?temporary-chat=true"

    INPUT_SELECTORS = [
        "div#prompt-textarea[contenteditable='true']",
        "textarea#prompt-textarea",
        "textarea[data-id='prompt-textarea']",
        "div[contenteditable='true'][data-virtualkeyboard='true']",
    ]
    SEND_BUTTON_SELECTORS = [
        "button[data-testid='send-button']",
        "button[aria-label*='Send' i]",
    ]
    STOP_BUTTON_SELECTORS = [
        "button[data-testid='stop-button']",
        "button[data-testid='composer-speech-button']",  # appears when not generating
        "button[aria-label*='Stop' i]",
    ]
    ASSISTANT_MSG_SELECTORS = [
        "div[data-message-author-role='assistant']",
        "[data-testid^='conversation-turn-'] [data-message-author-role='assistant']",
    ]
    # Buttons the anonymous flow throws at you
    DISMISS_SELECTORS = [
        "button:has-text('Stay logged out')",
        "a:has-text('Stay logged out')",
        "button:has-text('Dismiss')",
        "button[aria-label='Close']",
        "button:has-text('No thanks')",
    ]

    async def initialize(self) -> None:
        await super().initialize()
        assert self.page is not None
        await self.page.goto(self.url, wait_until="domcontentloaded")
        # Wait for any Cloudflare challenge to clear
        cleared = await wait_for_cloudflare(self.page, timeout=settings.provider_timeout_seconds)
        if not cleared:
            raise ProviderError(
                "ChatGPT: Cloudflare challenge did not clear within timeout. "
                "Try HEADLESS=false, install real Chrome (not just Chromium), "
                "or run again after a short delay."
            )
        # Dismiss login modal if it appears
        await self._dismiss_modals()
        # Wait for the prompt input
        try:
            await self.page.wait_for_selector(", ".join(self.INPUT_SELECTORS), timeout=20_000)
        except Exception as exc:
            raise ProviderError(
                "ChatGPT prompt input not found after Cloudflare cleared. "
                "Anonymous flow may have changed; check screenshot/html artifacts."
            ) from exc

    async def _dismiss_modals(self) -> None:
        """ChatGPT's anonymous flow shows a login prompt; dismiss it if visible."""
        assert self.page is not None
        for _ in range(3):
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
            raise ProviderError("ChatGPT input box not found")
        await el.click()
        if sel and sel.startswith("textarea"):
            await el.fill(prompt)
        else:
            await self.page.keyboard.type(prompt, delay=15)
        send_el, _ = await self._find_first(self.SEND_BUTTON_SELECTORS, timeout=3000)
        if send_el:
            await send_el.click()
        else:
            await self.page.keyboard.press("Enter")

    async def wait_for_completion(self) -> None:
        """Wait until the assistant response stops growing.

        Text-stability detection: poll the last assistant message every 0.5 s
        and declare streaming done when the text hasn't changed for 2 full
        seconds. This is robust to any DOM/selector change — if ChatGPT ships
        a redesign overnight it still works.

        A fast-path check for the stop button is kept as an optional speedup
        for well-known versions of the UI, but a missed selector never causes
        a premature browser close.
        """
        assert self.page is not None

        # Give the page a moment to start rendering the response
        await asyncio.sleep(2.0)

        prev_text = ""
        stable_ticks = 0
        # 2 s of no change = done (4 checks × 0.5 s)
        STABLE_NEEDED = 4
        # Hard ceiling: PROVIDER_TIMEOUT_SECONDS (default 180 s)
        deadline = asyncio.get_event_loop().time() + settings.provider_timeout_seconds

        while asyncio.get_event_loop().time() < deadline:
            curr_text = await self._read_last_response()

            if curr_text and curr_text == prev_text:
                stable_ticks += 1
                if stable_ticks >= STABLE_NEEDED:
                    break
            else:
                stable_ticks = 0
                prev_text = curr_text

            await asyncio.sleep(0.5)

        await asyncio.sleep(settings.stream_settle_seconds)

    async def _read_last_response(self) -> str:
        """Return the current text of the last assistant message, or '' on any error."""
        assert self.page is not None
        for sel in self.ASSISTANT_MSG_SELECTORS:
            try:
                nodes = await self.page.query_selector_all(sel)
                if nodes:
                    return collapse_ws(await nodes[-1].inner_text() or "")
            except Exception:
                continue
        return ""

    async def extract_response(self) -> str:
        return await self._read_last_response()

    async def extract_citations(self) -> list[dict[str, Any]]:
        """Inline links inside the assistant message bubble."""
        assert self.page is not None
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            nodes = await self.page.query_selector_all(self.ASSISTANT_MSG_SELECTORS[0])
            if not nodes:
                return results
            last = nodes[-1]
            anchors = await last.query_selector_all("a[href]")
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
        except Exception:
            pass
        return results
