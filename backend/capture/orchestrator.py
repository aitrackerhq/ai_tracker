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

from backend.config import settings
from backend.database.session import session_scope
from backend.models import Run, SteelProfile
from backend.processing.pipeline import process_batch
from backend.providers import PROVIDER_REGISTRY, BaseProvider
from backend.providers.stealth import USER_AGENT, apply_stealth
from backend.storage import backends as storage
from backend.utils.helpers import new_run_id

logger = logging.getLogger(__name__)


def _get_steel_profile(provider_name: str) -> str | None:
    """Return the persisted Steel profile id for a provider, or None if unset."""
    with session_scope() as db:
        row = db.get(SteelProfile, provider_name)
        return row.profile_id if row else None


def _set_steel_profile(provider_name: str, profile_id: str) -> None:
    """Upsert the Steel profile id for a provider so future captures reuse it."""
    with session_scope() as db:
        row = db.get(SteelProfile, provider_name)
        if row is None:
            db.add(SteelProfile(provider=provider_name, profile_id=profile_id))
        else:
            row.profile_id = profile_id


@asynccontextmanager
async def _steel_browser_context(provider_name: str) -> AsyncIterator[BrowserContext]:
    """Steel.dev managed browser: create a cloud session, connect over CDP, then
    release the session on exit. One session per provider — each gets its own
    residential identity, which suits our parallel-per-provider capture. Steel
    handles proxies + CAPTCHA + stealth, so we don't inject our own fingerprint
    patches (they'd fight Steel's managed profile).
    """
    from steel import Steel

    client = Steel(steel_api_key=settings.steel_api_key)
    # Plan-aware hardening: use_proxy/solve_captcha need a paid plan (sending them
    # on the free plan 400s), proxy_url is BYOP and works anywhere. Omitting all
    # three yields a bare session (fine for non-Cloudflare sites).
    create_kwargs: dict = {}
    if settings.steel_use_proxy:
        create_kwargs["use_proxy"] = True
    if settings.steel_solve_captcha:
        create_kwargs["solve_captcha"] = True
    if settings.steel_proxy_url:
        create_kwargs["proxy_url"] = settings.steel_proxy_url

    # Reuse this provider's persisted profile so Cloudflare clearance + reputation
    # carry over (free-tier reliability — clear the challenge once, then skip it).
    stored_profile = _get_steel_profile(provider_name) if settings.steel_persist_profile else None
    if settings.steel_persist_profile:
        create_kwargs["persist_profile"] = True
        if stored_profile:
            create_kwargs["profile_id"] = stored_profile

    # SDK calls are sync — run them off the event loop so concurrent providers
    # don't block each other while a session spins up.
    session = await asyncio.to_thread(client.sessions.create, **create_kwargs)
    logger.info(
        "steel session %s for %s (profile=%s, %s)",
        session.id, provider_name, session.profile_id or "none",
        {k: v for k, v in create_kwargs.items() if k != "profile_id"} or "bare",
    )
    # Persist a newly-minted profile id for next time.
    if settings.steel_persist_profile and session.profile_id and session.profile_id != stored_profile:
        _set_steel_profile(provider_name, session.profile_id)
    cdp_url = f"wss://connect.steel.dev?apiKey={settings.steel_api_key}&sessionId={session.id}"
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        try:
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            yield ctx
        finally:
            await browser.close()
            try:
                await asyncio.to_thread(client.sessions.release, session.id)
            except Exception:
                logger.warning("steel session release failed: %s", session.id)


@asynccontextmanager
async def _remote_browser_context(provider_name: str) -> AsyncIterator[BrowserContext]:
    """Connect to a managed stealth-browser service over CDP (BROWSER_REMOTE_CDP_URL).

    The service supplies residential IPs, stealth fingerprints, and CAPTCHA
    solving, so we skip the local launch args, PROXY_URL, and on-disk profiles —
    session/proxy management lives on the service side. Each connect typically
    opens a fresh remote session, which is exactly what our parallel-per-provider
    capture wants. No silent fallback to local: if this fails the run errors
    (a headless server has no display to fall back to).
    """
    logger.info("connecting to remote browser for %s (managed CDP endpoint)", provider_name)
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(settings.browser_remote_cdp_url)
        try:
            ctx = (
                browser.contexts[0]
                if browser.contexts
                else await browser.new_context(
                    viewport={"width": 1366, "height": 900},
                    user_agent=USER_AGENT,
                    locale="en-US",
                )
            )
            await apply_stealth(ctx)
            yield ctx
        finally:
            await browser.close()


@asynccontextmanager
async def browser_context(provider_name: str) -> AsyncIterator[BrowserContext]:
    """One persistent context per provider so Cloudflare clearance cookies + any
    optional session state persist across runs.

    Uses patchright (CDP-stealth) + real Chrome when available — required to
    pass Cloudflare Turnstile. Optional proxy (PROXY_URL) is wired in here as a
    rotation hook. Falls back to vanilla playwright + bundled Chromium.

    When a remote stealth browser is configured (STEEL_API_KEY or
    BROWSER_REMOTE_CDP_URL), connects to that managed service instead (the
    production / cloud path — no local Chrome window).
    """
    if settings.steel_api_key:
        async with _steel_browser_context(provider_name) as ctx:
            yield ctx
        return
    if settings.browser_remote_cdp_url:
        async with _remote_browser_context(provider_name) as ctx:
            yield ctx
        return

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
        """Bind the orchestrator to pre-created run rows; force_refresh bypasses the cache."""
        self.run_ids = run_ids
        self.force_refresh = force_refresh

    def _load_jobs(self) -> list[tuple[int, int, str, str, str | None]]:
        """Load (id, project_id, provider, prompt, geo) tuples for this batch's runs."""
        with session_scope() as db:
            rows = db.scalars(select(Run).where(Run.id.in_(self.run_ids))).all()
            return [(r.id, r.project_id, r.provider, r.prompt, r.geo_location) for r in rows]

    async def run(self) -> list[int]:
        """Capture phase only — providers run **concurrently** (each has its own
        isolated browser context / SerpAPI client). Within a provider, prompts
        stay sequential to honor rate limiting + the circuit breaker. Processing
        is a separate sequential phase (see pipeline.process_batch).

        Returns the attempted run_ids (now 'captured' or 'error').
        """
        jobs = self._load_jobs()
        by_provider: dict[str, list[tuple[int, int, str, str | None]]] = defaultdict(list)
        for run_pk, project_id, provider, prompt, geo in jobs:
            by_provider[provider].append((run_pk, project_id, prompt, geo))

        results = await asyncio.gather(
            *(self._capture_provider(p, pjobs) for p, pjobs in by_provider.items()),
            return_exceptions=True,
        )
        attempted: list[int] = []
        for provider_name, res in zip(by_provider.keys(), results, strict=True):
            if isinstance(res, BaseException):
                logger.exception("provider capture crashed: %s", provider_name, exc_info=res)
                continue
            attempted.extend(res)
        return attempted

    async def _capture_provider(
        self,
        provider_name: str,
        pjobs: list[tuple[int, int, str, str | None]],
    ) -> list[int]:
        """Capture all of one provider's runs: cache-resolve first, then execute
        the rest through the browser/SerpAPI. Returns the attempted run_ids."""
        attempted: list[int] = []
        remaining: list[tuple[int, str, str | None]] = []

        # cache resolution — skips the network entirely for fresh-enough results
        for run_pk, project_id, prompt, geo in pjobs:
            if not self.force_refresh:
                cached = find_cached_run(project_id, provider_name, prompt, geo, run_pk)
                if cached:
                    try:
                        await self._reuse_cached(run_pk, cached)
                        attempted.append(run_pk)
                        continue
                    except Exception:
                        logger.exception("cache reuse failed for run %s; capturing fresh", run_pk)
            remaining.append((run_pk, prompt, geo))

        if not remaining:
            return attempted

        cls = PROVIDER_REGISTRY.get(provider_name)
        if not cls:
            self._fail_all([pk for pk, _, _ in remaining], f"unknown provider: {provider_name}")
            return attempted + [pk for pk, _, _ in remaining]

        needs_browser = getattr(cls, "needs_browser", True)
        done: list[int] = []
        try:
            if needs_browser:
                async with browser_context(provider_name) as ctx:
                    await self._process_provider(cls, ctx, remaining, done)
            else:
                await self._process_provider(cls, None, remaining, done)
        except Exception as exc:
            logger.exception("provider batch failed: %s", provider_name)
            pending = [pk for pk, _, _ in remaining if pk not in done]
            self._fail_all(pending, repr(exc))
            done.extend(pending)
        return attempted + done

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
        """Capture one prompt with exponential-backoff retries; True on success."""
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
        """Run a single provider capture and persist its artifacts (status → captured)."""
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
            # Processing (NER + sentiment + ranking) is deferred to the sequential
            # process_batch phase so the parallel capture workers stay capture-only.
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
        # Processing is deferred to the sequential process_batch phase.
        logger.info("run %s served from cache", run_pk)

    def _set_status(self, run_pk: int, status: str) -> None:
        """Set a run's status."""
        with session_scope() as db:
            run = db.get(Run, run_pk)
            if run is not None:
                run.status = status

    def _set_error(self, run_pk: int, message: str) -> None:
        """Mark a run failed with an error message."""
        with session_scope() as db:
            run = db.get(Run, run_pk)
            if run is not None:
                run.status = "error"
                run.error = message

    def _fail_all(self, run_pks: list[int], message: str) -> None:
        """Mark every given run failed with the same message."""
        for pk in run_pks:
            self._set_error(pk, message)


def run_capture(run_ids: list[int], force_refresh: bool = False) -> list[int]:
    """In-process entry-point: capture (parallel across providers) then process
    (sequential, NER ∥ sentiment per run). Mirrors the Celery capture→chord flow
    in a single process. Operates on pre-created run rows."""
    captured = asyncio.run(CaptureOrchestrator(run_ids, force_refresh=force_refresh).run())
    process_batch(captured)
    return captured


def capture_provider(
    provider_name: str, run_ids: list[int], force_refresh: bool = False
) -> list[int]:
    """Capture-only sync entry-point for ONE provider (a Celery fan-out task).
    `run_ids` are the pre-created rows for `provider_name`. No processing —
    that runs later in the chord callback. Returns attempted run_ids."""
    orch = CaptureOrchestrator(run_ids, force_refresh=force_refresh)
    pjobs = [(pk, pid, prompt, geo) for pk, pid, _prov, prompt, geo in orch._load_jobs()]
    return asyncio.run(orch._capture_provider(provider_name, pjobs))
