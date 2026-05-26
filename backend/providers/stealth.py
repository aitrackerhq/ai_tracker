"""Shared anti-detection helpers.

Cloudflare's Turnstile challenge (used by ChatGPT and Google search occasionally)
checks for a handful of automation signals. We patch the most common ones at
page init time and provide a waiter that pauses while a challenge is solving.

This is best-effort: Cloudflare updates its detection constantly. Headed mode
(HEADLESS=false) clears challenges far more reliably than headless.
"""
from __future__ import annotations

import asyncio
import time

from playwright.async_api import BrowserContext, Page

# Realistic Chrome on macOS UA. The persistent context's underlying Chromium
# build advertises a slightly different UA which Cloudflare sometimes flags.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

# JS injected before every page load. Hides navigator.webdriver, normalises
# plugins/languages, and stubs window.chrome so headless detectors stop short.
STEALTH_INIT = r"""
(() => {
  // navigator.webdriver -> undefined
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  // languages
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

  // plugins (length > 0 looks human)
  Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map((i) => ({ name: 'Plugin ' + i }))
  });

  // window.chrome stub
  if (!window.chrome) {
    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
  }

  // permissions.query for notifications
  try {
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (p) =>
      p && p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(p);
  } catch (e) {}

  // WebGL vendor/renderer
  try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {
      if (parameter === 37445) return 'Intel Inc.';
      if (parameter === 37446) return 'Intel Iris OpenGL Engine';
      return getParameter.call(this, parameter);
    };
  } catch (e) {}
})();
"""


async def apply_stealth(context: BrowserContext) -> None:
    """Install stealth init script + extra HTTP headers on every page in the context."""
    await context.add_init_script(STEALTH_INIT)
    await context.set_extra_http_headers(
        {
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="129", "Not=A?Brand";v="8", "Google Chrome";v="129"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
        }
    )


async def wait_for_cloudflare(page: Page, timeout: float = 45.0) -> bool:
    """If a Cloudflare challenge is showing, wait until it clears.

    Returns True when the page is past the challenge, False if it never cleared
    within the timeout (call sites can decide whether to bail).
    """
    deadline = time.time() + timeout
    last_state: str | None = None
    while time.time() < deadline:
        # Title-based detection (fast & free)
        try:
            title = (await page.title() or "").lower()
        except Exception:
            title = ""
        challenged = (
            "just a moment" in title
            or "attention required" in title
            or "checking your browser" in title
        )

        # Iframe-based detection (Turnstile widget)
        if not challenged:
            try:
                cf = await page.query_selector("iframe[src*='challenges.cloudflare.com']")
                if cf and await cf.is_visible():
                    challenged = True
            except Exception:
                pass

        # Body class fallback
        if not challenged:
            try:
                body_class = await page.evaluate("document.body && document.body.className || ''")
                if "no-js" in (body_class or "") and "cf" in (body_class or ""):
                    challenged = True
            except Exception:
                pass

        if not challenged:
            return True

        if last_state != "waiting":
            last_state = "waiting"
        await asyncio.sleep(1.0)
    return False
