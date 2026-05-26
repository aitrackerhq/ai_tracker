from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

# patchright is a drop-in replacement for playwright that patches CDP-level
# fingerprints (the only thing JS stealth scripts cannot hide). This is what
# actually gets us past Cloudflare on ChatGPT and Google Search. Falls back to
# vanilla playwright if patchright isn't installed.
try:
    from patchright.async_api import async_playwright  # type: ignore[import-not-found]

    USING_PATCHRIGHT = True
except ImportError:  # pragma: no cover
    from playwright.async_api import async_playwright

    USING_PATCHRIGHT = False

from playwright.async_api import BrowserContext

from backend.config import settings
from backend.database.session import session_scope
from backend.models import Run
from backend.processing.pipeline import process_run
from backend.providers import PROVIDER_REGISTRY, BaseProvider, ProviderError
from backend.providers.stealth import USER_AGENT, apply_stealth
from backend.storage import raw_store
from backend.utils.helpers import new_run_id

logger = logging.getLogger(__name__)


@asynccontextmanager
async def browser_context(provider_name: str) -> AsyncIterator[BrowserContext]:
    """One persistent context per provider so Cloudflare clearance cookies + any
    optional session state persist across runs.

    Uses patchright (CDP-stealth) + real Chrome when available — required to
    pass Cloudflare Turnstile on chatgpt.com and Google Search. Falls back to
    vanilla playwright + bundled Chromium otherwise (will likely get challenged).
    """
    profile_dir = settings.browser_user_data_dir / provider_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    if USING_PATCHRIGHT:
        # patchright handles automation-flag hiding at the CDP level. Keep
        # launch args minimal — the noisy override flags it doesn't need are
        # themselves detectable, so we let patchright manage defaults.
        launch_args: list[str] = ["--no-first-run", "--no-default-browser-check"]
        ignore_default: list[str] = []
    else:
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--no-first-run",
        ]
        ignore_default = ["--enable-automation"]

    logger.info(
        "launching browser for %s (patchright=%s, headless=%s)",
        provider_name,
        USING_PATCHRIGHT,
        settings.headless,
    )

    async with async_playwright() as pw:
        common_kwargs = dict(
            user_data_dir=str(profile_dir),
            headless=settings.headless,
            viewport={"width": 1366, "height": 900},
            user_agent=USER_AGENT,
            locale="en-US",
            timezone_id="America/New_York",
            args=launch_args,
            ignore_default_args=ignore_default,
        )
        # Prefer real Chrome (`channel="chrome"`); fall back to bundled Chromium.
        try:
            ctx = await pw.chromium.launch_persistent_context(channel="chrome", **common_kwargs)
        except Exception as exc:
            logger.info("real Chrome unavailable (%s); falling back to bundled browser", exc)
            ctx = await pw.chromium.launch_persistent_context(**common_kwargs)

        # JS-level stealth is still useful even with patchright — patchright
        # patches CDP, this patches the page DOM. They're complementary.
        await apply_stealth(ctx)
        try:
            yield ctx
        finally:
            await ctx.close()


class CaptureOrchestrator:
    """Runs a batch of (provider, prompt) jobs."""

    def __init__(self, project_id: int, prompts: list[str], providers: list[str]):
        self.project_id = project_id
        self.prompts = prompts
        self.providers = providers

    async def run(self) -> list[int]:
        run_ids: list[int] = []
        for provider_name in self.providers:
            cls = PROVIDER_REGISTRY.get(provider_name)
            if not cls:
                logger.warning("unknown provider: %s", provider_name)
                continue
            # API-based providers (e.g. google_ai via SerpAPI) signal they don't
            # need a browser by setting the class attribute `needs_browser = False`.
            if getattr(cls, "needs_browser", True):
                async with browser_context(provider_name) as ctx:
                    for prompt in self.prompts:
                        run_id_pk = await self._run_one(cls, ctx, provider_name, prompt)
                        if run_id_pk is not None:
                            run_ids.append(run_id_pk)
            else:
                # No browser — pass None as context; provider ignores it.
                for prompt in self.prompts:
                    run_id_pk = await self._run_one(cls, None, provider_name, prompt)
                    if run_id_pk is not None:
                        run_ids.append(run_id_pk)
        return run_ids

    async def _run_one(
        self,
        cls: type[BaseProvider],
        ctx: BrowserContext,
        provider_name: str,
        prompt: str,
    ) -> int | None:
        run_uid = new_run_id()
        provider = cls(ctx)
        run_pk: int | None = None
        try:
            with session_scope() as db:
                run = Run(
                    project_id=self.project_id,
                    provider=provider_name,
                    prompt=prompt,
                    status="running",
                )
                db.add(run)
                db.flush()
                run_pk = run.id

            await provider.initialize()
            result = await provider.capture(prompt, run_uid)
            raw_path = raw_store.write(run_uid, result.to_dict())

            with session_scope() as db:
                run = db.get(Run, run_pk)
                if run is not None:
                    run.raw_json_path = str(raw_path)
                    run.screenshot_path = result.screenshot_path
                    run.html_path = result.html_path
                    run.status = "captured"

            # process immediately (still a separate layer — orchestrator just chains them)
            process_run(run_pk)

        except ProviderError as exc:
            logger.exception("provider error")
            with session_scope() as db:
                run = db.get(Run, run_pk) if run_pk else None
                if run is not None:
                    run.status = "error"
                    run.error = str(exc)
        except Exception as exc:
            logger.exception("capture failed")
            with session_scope() as db:
                run = db.get(Run, run_pk) if run_pk else None
                if run is not None:
                    run.status = "error"
                    run.error = repr(exc)
        finally:
            await provider.close()
        return run_pk


def run_capture(project_id: int, prompts: list[str], providers: list[str]) -> list[int]:
    """Sync entry-point for background tasks."""
    return asyncio.run(CaptureOrchestrator(project_id, prompts, providers).run())
