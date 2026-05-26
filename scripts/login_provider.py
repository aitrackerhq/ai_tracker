"""Optional: opens a real browser so you can log into a provider. Session
persists to BROWSER_USER_DATA_DIR and is reused by automated captures.

All providers (chatgpt, gemini, google_ai) run anonymously by default — you
do NOT need this script for normal use. It only helps when you want a
signed-in session for higher rate limits or account-gated features.

Usage:
    python -m scripts.login_provider chatgpt
    python -m scripts.login_provider gemini
"""
from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright

from backend.config import settings

URLS = {
    "chatgpt": "https://chatgpt.com/",      # optional
    "gemini": "https://gemini.google.com/app",  # required (no anonymous mode)
}


async def main(provider: str) -> None:
    if provider not in URLS:
        print(f"unknown provider: {provider}. choices: {list(URLS)}")
        sys.exit(2)
    profile_dir = settings.browser_user_data_dir / provider
    profile_dir.mkdir(parents=True, exist_ok=True)
    print(f"launching headed browser → {URLS[provider]}")
    print(f"profile: {profile_dir}")
    print("log in, then close the browser window when finished.")
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await ctx.new_page()
        await page.goto(URLS[provider])
        try:
            # wait until user closes the browser
            await ctx.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            await ctx.close()
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m scripts.login_provider [chatgpt|gemini]")
        sys.exit(2)
    asyncio.run(main(sys.argv[1].lower()))
