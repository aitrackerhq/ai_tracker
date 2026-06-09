"""Smoke-test the remote stealth-browser (STEEL_API_KEY or BROWSER_REMOTE_CDP_URL).

Connects to the managed service, opens a page, navigates, and reads the title —
confirming credentials + connectivity before a real capture run.

    python -m scripts.check_browser

If neither is set, browser providers launch Chrome locally, so there is nothing
remote to check (exits 0).

Note: this verifies the connection only. A clean navigation to example.com does
NOT prove Cloudflare/Turnstile bypass — that's validated by an actual capture
against ChatGPT/Perplexity/Google.
"""
from __future__ import annotations

import asyncio
import sys

from backend.config import settings


async def _round_trip() -> str:
    from backend.capture.orchestrator import browser_context

    async with browser_context("smoke-test") as ctx:
        page = await ctx.new_page()
        try:
            await page.goto("https://example.com", wait_until="domcontentloaded", timeout=60_000)
            return await page.title()
        finally:
            await page.close()


def main() -> int:
    if not settings.browser_remote:
        print("No remote browser set (STEEL_API_KEY / BROWSER_REMOTE_CDP_URL) — "
              "browser providers launch Chrome locally.")
        return 0

    service = "Steel.dev" if settings.steel_api_key else "remote CDP endpoint"
    print(f"service  : {service}")
    print("-" * 48)
    try:
        title = asyncio.run(_round_trip())
        print(f"PASS  connected + navigated (page title: {title!r})")
        print("-" * 48)
        print("OK: remote browser round-trip succeeded.")
        return 0
    except Exception as exc:  # noqa: BLE001 — surface the connection error verbatim
        print(f"FAIL  {exc}")
        print("-" * 48)
        print("FAILED: check the endpoint URL / API key.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
