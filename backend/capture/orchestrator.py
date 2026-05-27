from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import select

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


def create_pending_runs(
    project_id: int, prompts: list[str], providers: list[str]
) -> tuple[str, list[int]]:
    """Create one pending Run row per (provider × prompt) before any work starts.

    Returns (batch_id, run_ids). The frontend can immediately render the full
    pipeline (including not-yet-started steps) by polling this batch.
    """
    batch_id = uuid.uuid4().hex[:12]
    run_ids: list[int] = []
    with session_scope() as db:
        for provider in providers:
            for prompt in prompts:
                run = Run(
                    project_id=project_id,
                    provider=provider,
                    prompt=prompt,
                    status="pending",
                    batch_id=batch_id,
                )
                db.add(run)
                db.flush()
                run_ids.append(run.id)
    return batch_id, run_ids


class CaptureOrchestrator:
    """Executes a set of pre-created Run rows, grouped by provider so each
    provider's browser context is launched once and reused across its prompts.
    """

    def __init__(self, run_ids: list[int]):
        self.run_ids = run_ids

    async def run(self) -> list[int]:
        with session_scope() as db:
            rows = db.scalars(select(Run).where(Run.id.in_(self.run_ids))).all()
            jobs = [(r.id, r.provider, r.prompt) for r in rows]

        by_provider: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for run_pk, provider, prompt in jobs:
            by_provider[provider].append((run_pk, prompt))

        done: list[int] = []
        for provider_name, plist in by_provider.items():
            cls = PROVIDER_REGISTRY.get(provider_name)
            if not cls:
                self._fail_all([pk for pk, _ in plist], f"unknown provider: {provider_name}")
                continue
            needs_browser = getattr(cls, "needs_browser", True)
            try:
                if needs_browser:
                    async with browser_context(provider_name) as ctx:
                        for run_pk, prompt in plist:
                            await self._run_one(cls, ctx, run_pk, prompt)
                            done.append(run_pk)
                else:
                    for run_pk, prompt in plist:
                        await self._run_one(cls, None, run_pk, prompt)
                        done.append(run_pk)
            except Exception as exc:
                # e.g. browser failed to launch for the whole provider
                logger.exception("provider batch failed: %s", provider_name)
                self._fail_all([pk for pk, _ in plist if pk not in done], repr(exc))
        return done

    async def _run_one(
        self,
        cls: type[BaseProvider],
        ctx: BrowserContext | None,
        run_pk: int,
        prompt: str,
    ) -> None:
        run_uid = new_run_id()
        provider = cls(ctx)  # type: ignore[arg-type]
        try:
            self._set_status(run_pk, "running")
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

            # processing is a separate layer; orchestrator just chains the call
            process_run(run_pk)
            self._set_status(run_pk, "processed")

        except ProviderError as exc:
            logger.exception("provider error")
            self._set_error(run_pk, str(exc))
        except Exception as exc:
            logger.exception("capture failed")
            self._set_error(run_pk, repr(exc))
        finally:
            await provider.close()

    def _set_status(self, run_pk: int, status: str) -> None:
        with session_scope() as db:
            run = db.get(Run, run_pk)
            if run is not None:
                run.status = status

    def _set_error(self, run_pk: int, message: str) -> None:
        with session_scope() as db:
            run = db.get(Run, run_pk)
            if run is not None:
                run.status = "error"
                run.error = message

    def _fail_all(self, run_pks: list[int], message: str) -> None:
        for pk in run_pks:
            self._set_error(pk, message)


def run_capture(run_ids: list[int]) -> list[int]:
    """Sync entry-point for background tasks. Operates on pre-created run rows."""
    return asyncio.run(CaptureOrchestrator(run_ids).run())
