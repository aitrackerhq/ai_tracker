from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncIterator

from sqlalchemy import select

# patchright is a drop-in replacement for playwright that patches CDP-level
# fingerprints (the only thing JS stealth scripts cannot hide). This is what
# actually gets us past Cloudflare on ChatGPT, Perplexity, and Google Search.
# Falls back to vanilla playwright if patchright isn't installed.
try:
    from patchright.async_api import async_playwright  # type: ignore[import-not-found]

    USING_PATCHRIGHT = True
except ImportError:  # pragma: no cover
    from playwright.async_api import async_playwright

    USING_PATCHRIGHT = False

from playwright.async_api import BrowserContext

from backend.capture.competitors import detect_competitors_for_project
from backend.config import settings
from backend.database.session import session_scope
from backend.models import Run
from backend.processing.pipeline import process_run
from backend.providers import PROVIDER_REGISTRY, BaseProvider
from backend.providers.stealth import USER_AGENT, apply_stealth
from backend.storage import backends as storage
from backend.utils.helpers import new_run_id

logger = logging.getLogger(__name__)


@asynccontextmanager
async def browser_context(provider_name: str) -> AsyncIterator[BrowserContext]:
    """One persistent context per provider so Cloudflare clearance cookies + any
    optional session state persist across runs.

    Uses patchright (CDP-stealth) + real Chrome when available — required to
    pass Cloudflare Turnstile. Optional proxy (PROXY_URL) is wired in here as a
    rotation hook. Falls back to vanilla playwright + bundled Chromium.
    """
    profile_dir = settings.browser_user_data_dir / provider_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    if USING_PATCHRIGHT:
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
        "launching browser for %s (patchright=%s, headless=%s, proxy=%s)",
        provider_name,
        USING_PATCHRIGHT,
        settings.headless,
        bool(settings.proxy_url),
    )

    async with async_playwright() as pw:
        common_kwargs: dict = dict(
            user_data_dir=str(profile_dir),
            headless=settings.headless,
            viewport={"width": 1366, "height": 900},
            user_agent=USER_AGENT,
            locale="en-US",
            timezone_id="America/New_York",
            args=launch_args,
            ignore_default_args=ignore_default,
        )
        if settings.proxy_url:
            common_kwargs["proxy"] = {"server": settings.proxy_url}

        try:
            ctx = await pw.chromium.launch_persistent_context(channel="chrome", **common_kwargs)
        except Exception as exc:
            logger.info("real Chrome unavailable (%s); falling back to bundled browser", exc)
            ctx = await pw.chromium.launch_persistent_context(**common_kwargs)

        await apply_stealth(ctx)
        try:
            yield ctx
        finally:
            await ctx.close()


def create_pending_runs(
    project_id: int,
    prompts: list[str],
    providers: list[str],
    geo_location: str | None = None,
) -> tuple[str, list[int]]:
    """Create one pending Run row per (provider × prompt) before any work starts.

    Returns (batch_id, run_ids) so the dashboard can render the full pipeline
    (including not-yet-started steps) immediately by polling this batch.
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
                    geo_location=geo_location,
                )
                db.add(run)
                db.flush()
                run_ids.append(run.id)
    return batch_id, run_ids


def find_cached_run(
    project_id: int, provider: str, prompt: str, geo_location: str | None, exclude_run_id: int
) -> dict | None:
    """Return artifact paths from a recent successful run for the same
    (project, provider, prompt, geo) within the cache TTL, else None."""
    cutoff = datetime.utcnow() - timedelta(hours=settings.cache_ttl_hours)
    with session_scope() as db:
        candidates = db.scalars(
            select(Run)
            .where(
                Run.project_id == project_id,
                Run.provider == provider,
                Run.prompt == prompt,
                Run.status.in_(("captured", "processed")),
                Run.raw_json_path.is_not(None),
                Run.created_at >= cutoff,
                Run.id != exclude_run_id,
            )
            .order_by(Run.created_at.desc())
        ).all()
        for r in candidates:
            if (r.geo_location or None) == (geo_location or None):
                # only raw_json_path is reused; cached runs don't share heavy artifacts
                return {"raw_json_path": r.raw_json_path}
    return None


class CaptureOrchestrator:
    """Executes pre-created Run rows with caching, per-provider rate limiting,
    exponential backoff retries, and a circuit breaker.
    """

    def __init__(self, run_ids: list[int], force_refresh: bool = False):
        self.run_ids = run_ids
        self.force_refresh = force_refresh

    async def run(self) -> list[int]:
        with session_scope() as db:
            rows = db.scalars(select(Run).where(Run.id.in_(self.run_ids))).all()
            jobs = [(r.id, r.project_id, r.provider, r.prompt, r.geo_location) for r in rows]

        done: list[int] = []
        remaining: dict[str, list[tuple[int, str, str | None]]] = defaultdict(list)

        # 1) cache resolution — skips the network entirely for fresh-enough results
        for run_pk, project_id, provider, prompt, geo in jobs:
            if not self.force_refresh:
                cached = find_cached_run(project_id, provider, prompt, geo, run_pk)
                if cached:
                    try:
                        await self._reuse_cached(run_pk, cached)
                        done.append(run_pk)
                        continue
                    except Exception:
                        logger.exception("cache reuse failed for run %s; capturing fresh", run_pk)
            remaining[provider].append((run_pk, prompt, geo))

        # 2) execute remaining jobs grouped by provider
        for provider_name, plist in remaining.items():
            cls = PROVIDER_REGISTRY.get(provider_name)
            if not cls:
                self._fail_all([pk for pk, _, _ in plist], f"unknown provider: {provider_name}")
                done.extend(pk for pk, _, _ in plist)
                continue
            needs_browser = getattr(cls, "needs_browser", True)
            try:
                if needs_browser:
                    async with browser_context(provider_name) as ctx:
                        await self._process_provider(cls, ctx, plist, done)
                else:
                    await self._process_provider(cls, None, plist, done)
            except Exception as exc:
                logger.exception("provider batch failed: %s", provider_name)
                pending = [pk for pk, _, _ in plist if pk not in done]
                self._fail_all(pending, repr(exc))
                done.extend(pending)

        # 3) project-level LLM competitor auto-detection (best-effort)
        project_ids = {pid for _, pid, _, _, _ in jobs}
        for pid in project_ids:
            try:
                await detect_competitors_for_project(pid)
            except Exception:
                logger.exception("competitor detection failed for project %s", pid)
        return done

    async def _process_provider(
        self,
        cls: type[BaseProvider],
        ctx: BrowserContext | None,
        plist: list[tuple[int, str, str | None]],
        done: list[int],
    ) -> None:
        """Run a provider's jobs sequentially with rate limiting + circuit breaker."""
        consecutive_failures = 0
        for i, (run_pk, prompt, geo) in enumerate(plist):
            if consecutive_failures >= settings.circuit_breaker_threshold:
                self._set_error(
                    run_pk,
                    f"circuit breaker open ({consecutive_failures} consecutive failures)",
                )
                done.append(run_pk)
                continue

            # rate limit: space out requests to the same provider
            if i > 0 and settings.provider_min_delay_seconds > 0:
                await asyncio.sleep(settings.provider_min_delay_seconds)

            ok = await self._run_one_with_retry(cls, ctx, run_pk, prompt, geo)
            done.append(run_pk)
            consecutive_failures = 0 if ok else consecutive_failures + 1

    async def _run_one_with_retry(
        self,
        cls: type[BaseProvider],
        ctx: BrowserContext | None,
        run_pk: int,
        prompt: str,
        geo: str | None,
    ) -> bool:
        attempts = settings.provider_max_retries + 1
        last_err = "unknown error"
        for attempt in range(attempts):
            try:
                await self._capture_once(cls, ctx, run_pk, prompt, geo)
                return True
            except Exception as exc:
                last_err = repr(exc)
                if attempt < attempts - 1:
                    backoff = settings.provider_backoff_base ** attempt
                    logger.warning(
                        "run %s attempt %d/%d failed (%s); backing off %.1fs",
                        run_pk, attempt + 1, attempts, last_err, backoff,
                    )
                    await asyncio.sleep(backoff)
        self._set_error(run_pk, last_err)
        return False

    async def _capture_once(
        self,
        cls: type[BaseProvider],
        ctx: BrowserContext | None,
        run_pk: int,
        prompt: str,
        geo: str | None,
    ) -> None:
        run_uid = new_run_id()
        provider = cls(ctx, geo_location=geo)
        try:
            self._set_status(run_pk, "running")
            await provider.initialize()
            result = await provider.capture(prompt, run_uid)
            # persist artifacts through the storage backend (local disk or R2)
            raw_ref = storage.put_json("raw", run_uid, result.to_dict())
            screenshot_ref = (
                storage.put_artifact("screenshots", run_uid, result.screenshot_path)
                if result.screenshot_path
                else None
            )
            html_ref = (
                storage.put_artifact("html", run_uid, result.html_path)
                if result.html_path
                else None
            )
            with session_scope() as db:
                run = db.get(Run, run_pk)
                if run is not None:
                    run.raw_json_path = raw_ref
                    run.screenshot_path = screenshot_ref
                    run.html_path = html_ref
                    run.status = "captured"
            process_run(run_pk)  # NER + ranking + local sentiment (processing layer)
            self._set_status(run_pk, "processed")
        finally:
            await provider.close()

    async def _reuse_cached(self, run_pk: int, cached: dict) -> None:
        """Reuse a prior run's raw artifact instead of re-capturing."""
        raw_data = storage.load_json(cached["raw_json_path"])
        new_uid = new_run_id()
        new_ref = storage.put_json("raw", new_uid, raw_data)
        with session_scope() as db:
            run = db.get(Run, run_pk)
            if run is not None:
                run.raw_json_path = new_ref
                # Don't share the source run's screenshot/HTML refs: TTL purge
                # deletes artifacts per stale run, which would break a younger
                # cached run pointing at the same file. The copied raw JSON is
                # enough for analytics/reprocessing; the screenshot is a duplicate.
                run.screenshot_path = None
                run.html_path = None
                run.cached = True
                run.status = "captured"
        process_run(run_pk)  # NER + ranking + local sentiment (processing layer)
        self._set_status(run_pk, "processed")
        logger.info("run %s served from cache", run_pk)

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


def run_capture(run_ids: list[int], force_refresh: bool = False) -> list[int]:
    """Sync entry-point for background tasks. Operates on pre-created run rows."""
    return asyncio.run(CaptureOrchestrator(run_ids, force_refresh=force_refresh).run())
