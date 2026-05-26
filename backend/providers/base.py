from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page

from backend.config import settings
from backend.utils.helpers import collapse_ws, domain_from_url, human_pause, utc_now_iso


class ProviderError(Exception):
    pass


@dataclass
class CaptureResult:
    provider: str
    prompt: str
    timestamp: str
    response_text: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    screenshot_path: str | None = None
    html_path: str | None = None
    has_ai_overview: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "prompt": self.prompt,
            "timestamp": self.timestamp,
            "response_text": self.response_text,
            "citations": self.citations,
            "links": self.links,
            "metadata": self.metadata,
            "screenshot_path": self.screenshot_path,
            "html_path": self.html_path,
            "has_ai_overview": self.has_ai_overview,
        }


class BaseProvider:
    """Adapter interface every provider implements."""

    name: str = "base"

    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Page | None = None

    async def initialize(self) -> None:
        self.page = await self.context.new_page()
        self.page.set_default_timeout(settings.provider_timeout_seconds * 1000)

    async def close(self) -> None:
        if self.page is not None:
            try:
                await self.page.close()
            except Exception:
                pass
            self.page = None

    async def capture(self, prompt: str, run_id: str) -> CaptureResult:
        """Default: navigate, send prompt, wait, extract, save artifacts."""
        assert self.page is not None, "call initialize() first"
        started = asyncio.get_event_loop().time()
        await self.send_prompt(prompt)
        await self.wait_for_completion()
        response_text = await self.extract_response()
        citations = await self.extract_citations()
        links = await self.extract_links()
        screenshot_path, html_path = await self.save_artifacts(run_id)
        elapsed = round(asyncio.get_event_loop().time() - started, 2)

        return CaptureResult(
            provider=self.name,
            prompt=prompt,
            timestamp=utc_now_iso(),
            response_text=collapse_ws(response_text),
            citations=citations,
            links=links,
            metadata={
                "response_time": elapsed,
                "has_citations": bool(citations),
            },
            screenshot_path=str(screenshot_path) if screenshot_path else None,
            html_path=str(html_path) if html_path else None,
        )

    # subclasses override below
    async def send_prompt(self, prompt: str) -> None:
        raise NotImplementedError

    async def wait_for_completion(self) -> None:
        raise NotImplementedError

    async def extract_response(self) -> str:
        raise NotImplementedError

    async def extract_citations(self) -> list[dict[str, Any]]:
        return []

    async def extract_links(self) -> list[dict[str, Any]]:
        assert self.page is not None
        try:
            anchors = await self.page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({href: e.href, text: e.innerText || ''}))",
            )
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for a in anchors:
            href = (a.get("href") or "").strip()
            if not href or href.startswith("javascript:") or href.startswith("#"):
                continue
            d = domain_from_url(href)
            if not d:
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append({"url": href, "domain": d, "text": collapse_ws(a.get("text", ""))[:200]})
        return out

    async def save_artifacts(self, run_id: str) -> tuple[Path | None, Path | None]:
        assert self.page is not None
        screenshot_path = settings.screenshots_dir / f"{run_id}.png"
        html_path = settings.html_dir / f"{run_id}.html"
        try:
            await self.page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            screenshot_path = None
        try:
            html = await self.page.content()
            html_path.write_text(html, encoding="utf-8")
        except Exception:
            html_path = None
        return screenshot_path, html_path

    async def type_human(self, selector: str, text: str) -> None:
        assert self.page is not None
        el = await self.page.wait_for_selector(selector, state="visible")
        await el.click()
        for ch in text:
            await el.type(ch)
            await human_pause()
