from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from backend.auth import AuthDep

from backend.analytics import AnalyticsService
from backend.api.schemas import (
    CaptureRequest,
    ProjectCreate,
    ProjectOut,
    SuggestPromptsBody,
)
from backend.capture import create_pending_runs
from backend.capture.competitors import detect_competitors_for_project
from backend.config import settings
from backend.database.session import session_scope
from backend.llm import gemini, service as llm_service
from backend.models import Competitor, Project, Prompt
from backend.providers import PROVIDER_REGISTRY
from backend.storage import backends as storage
from backend.storage import purge_run_files
from backend.tasks import submit_capture, submit_reprocess

router = APIRouter(prefix="/api")


# ---------- projects ----------
# Creates a project owned by the authenticated user.
@router.post("/projects", response_model=ProjectOut)
def create_project(
    payload: ProjectCreate,
    current_user: AuthDep,
) -> ProjectOut:
    if not payload.name or not payload.domain:
        raise HTTPException(400, "name and domain are required")
    with session_scope() as db:
        valid_providers = [p for p in payload.providers if p in PROVIDER_REGISTRY]
        proj = Project(
            user_id=current_user.id,
            name=payload.name.strip(),
            domain=payload.domain.strip().lower(),
            geo_location=(payload.geo_location or "").strip() or None,
            providers=",".join(valid_providers) or None,
        )
        db.add(proj)
        db.flush()
        for p in payload.prompts[:5]:
            if p.strip():
                db.add(Prompt(project_id=proj.id, prompt_text=p.strip()))
        for c in payload.competitors:
            if c.strip():
                db.add(Competitor(project_id=proj.id, competitor_name=c.strip(), inferred=False))
        db.flush()
        return _project_to_out(proj)

# Returns only projects owned by the authenticated user.
@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    current_user: AuthDep,
) -> list[ProjectOut]:
    with session_scope() as db:
        projects = db.scalars(
    select(Project)
    .where(Project.user_id == current_user.id)
    .order_by(Project.created_at.desc())
).all()
        return [_project_to_out(p) for p in projects]

# Returns a project only if it belongs to the authenticated user.
@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    current_user: AuthDep,
) -> ProjectOut:
    with session_scope() as db:
        proj = db.scalar(
    select(Project)
    .where(Project.id == project_id)
    .where(Project.user_id == current_user.id)
)
        if proj is None:
            raise HTTPException(404, "project not found")
        return _project_to_out(proj)

# Deletes a project owned by the authenticated user.
@router.delete("/projects/{project_id}")
def delete_project(
    project_id: int,
    current_user: AuthDep,
) -> dict:
    with session_scope() as db:
        proj = db.scalar(
    select(Project)
    .where(Project.id == project_id)
    .where(Project.user_id == current_user.id)
)
        if proj is None:
            raise HTTPException(404, "project not found")
        # remove on-disk artifacts first so deleting a project doesn't orphan files
        files_removed = sum(purge_run_files(r) for r in proj.runs)
        db.delete(proj)
    return {"ok": True, "files_removed": files_removed}


def _project_to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        domain=p.domain,
        prompts=[pr.prompt_text for pr in p.prompts],
        competitors=[c.competitor_name for c in p.competitors],
        geo_location=p.geo_location,
        providers=[s for s in (p.providers or "").split(",") if s],
        created_at=p.created_at.isoformat() + "Z",
    )

# ---- helper right after _project_to_out ----

def _get_owned_project(db, project_id: int, user_id: str) -> Project:
    """
    Return the project if it exists and is owned by the given user.

    Raises HTTP 404 for both missing projects and ownership mismatches —
    deliberately indistinguishable to avoid leaking project existence to
    unauthorized callers.
    """
    proj = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.user_id == user_id)
    )
    if proj is None:
        raise HTTPException(404, "project not found")
    return proj


# ---------- capture ----------

@router.post("/projects/{project_id}/capture")
def trigger_capture(
    project_id: int,
    payload: CaptureRequest,
    bg: BackgroundTasks,
    current_user: AuthDep,
) -> dict:
    with session_scope() as db:
        proj = _get_owned_project(db, project_id, current_user.id)
        prompts = payload.prompts or [p.prompt_text for p in proj.prompts]
        # geo precedence: request override → project default → global default
        geo = payload.geo_location or proj.geo_location or settings.default_geo_location

    if not prompts:
        raise HTTPException(400, "no prompts to run")

    unknown = [p for p in payload.providers if p not in PROVIDER_REGISTRY]
    if unknown:
        raise HTTPException(400, f"unknown providers: {unknown}")

    # Persist the chosen providers as the project's default for next time.
    with session_scope() as db:
        proj = _get_owned_project(db, project_id, current_user.id)
        if payload.providers:
            proj.providers = ",".join(payload.providers)

    # Pre-create all (provider × prompt) runs as "pending" so the dashboard can
    # render the full pipeline immediately, then dispatch to a worker (Celery) or
    # an in-process background task when no broker is configured.
    batch_id, run_ids = create_pending_runs(project_id, prompts, payload.providers, geo)
    mode = submit_capture(run_ids, payload.force_refresh, bg)
    return {
        "ok": True,
        "batch_id": batch_id,
        "run_ids": run_ids,
        "providers": payload.providers,
        "prompts": len(prompts),
        "geo_location": geo,
        "force_refresh": payload.force_refresh,
        "mode": mode,
    }


@router.post("/projects/{project_id}/reprocess")
def reprocess(project_id: int, bg: BackgroundTasks, current_user: AuthDep) -> dict:
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    mode, count = submit_reprocess(project_id, bg)
    return {"ok": True, "mode": mode, "reprocessed": count}


# ---------- LLM intelligence ----------

@router.get("/llm/status")
def llm_status() -> dict:
    return {"configured": gemini.is_configured(), "model": settings.gemini_model}


@router.post("/llm/suggest-prompts")
async def suggest_prompts_adhoc(body: SuggestPromptsBody) -> dict:
    """Project-less suggestions for the new-project form (no project exists yet)."""
    if not gemini.is_configured():
        raise HTTPException(400, "GEMINI_API_KEY is not set")
    if not body.domain.strip():
        raise HTTPException(400, "domain is required")
    suggestions = await llm_service.suggest_prompts(
        body.domain.strip(), body.existing_prompts, body.competitors
    )
    return {"suggestions": suggestions}


@router.post("/projects/{project_id}/suggest-prompts")
async def suggest_prompts(project_id: int, current_user: AuthDep) -> dict:
    if not gemini.is_configured():
        raise HTTPException(400, "GEMINI_API_KEY is not set")
    with session_scope() as db:
        proj = _get_owned_project(db, project_id, current_user.id)
        domain = proj.domain
        existing = [p.prompt_text for p in proj.prompts]
        competitors = [c.competitor_name for c in proj.competitors]
    suggestions = await llm_service.suggest_prompts(domain, existing, competitors)
    return {"suggestions": suggestions}


class AddPromptsBody(BaseModel):
    prompts: list[str]


@router.post("/projects/{project_id}/prompts")
def add_prompts(project_id: int, body: AddPromptsBody, current_user: AuthDep) -> dict:
    with session_scope() as db:
        proj = _get_owned_project(db, project_id, current_user.id)
        existing = {p.prompt_text.strip().lower() for p in proj.prompts}
        added = 0
        for text in body.prompts:
            t = text.strip()
            if t and t.lower() not in existing:
                db.add(Prompt(project_id=project_id, prompt_text=t))
                existing.add(t.lower())
                added += 1
    return {"ok": True, "added": added}


@router.post("/projects/{project_id}/detect-competitors")
async def detect_competitors(project_id: int, current_user: AuthDep) -> dict:
    if not gemini.is_configured():
        raise HTTPException(400, "GEMINI_API_KEY is not set")
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    added = await detect_competitors_for_project(project_id)
    return {"ok": True, "added": added}


# ---------- analytics ----------

@router.get("/projects/{project_id}/overview")
def overview(project_id: int, current_user: AuthDep) -> dict:
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    data = AnalyticsService.overview(project_id)
    if not data:
        raise HTTPException(404, "project not found")
    return data


@router.get("/projects/{project_id}/runs")
def runs(project_id: int, current_user: AuthDep) -> list[dict]:
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    return AnalyticsService.runs(project_id)


@router.get("/runs/{run_id}")
def run_detail(run_id: int, current_user: AuthDep) -> dict:
    from backend.models import Run
    with session_scope() as db:
        r = db.scalar(
            select(Run)
            .join(Project)
            .where(Run.id == run_id)
            .where(Project.user_id == current_user.id)
        )
        if r is None:
            raise HTTPException(404, "run not found")
    data = AnalyticsService.run_detail(run_id)
    if data is None:
        raise HTTPException(404, "run not found")
    return data


@router.get("/projects/{project_id}/competitors")
def competitors(project_id: int, current_user: AuthDep) -> dict:
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    return AnalyticsService.competitors(project_id)


@router.get("/projects/{project_id}/providers")
def provider_comparison(project_id: int, current_user: AuthDep) -> dict:
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    return AnalyticsService.provider_comparison(project_id)


@router.get("/projects/{project_id}/timeseries")
def timeseries(project_id: int, current_user: AuthDep) -> dict:
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    return AnalyticsService.timeseries(project_id)


@router.get("/projects/{project_id}/history")
def history(project_id: int, current_user: AuthDep) -> dict:
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    return AnalyticsService.history(project_id)


@router.get("/projects/{project_id}/framing-context")
def framing_context(project_id: int, current_user: AuthDep) -> dict:
    with session_scope() as db:
        _get_owned_project(db, project_id, current_user.id)
    return AnalyticsService.framing_context(project_id)


# ---------- artifacts ----------

@router.get("/artifacts/screenshot/{run_id}")
def get_screenshot(run_id: int, current_user: AuthDep):
    with session_scope() as db:
        from backend.models import Run

        r = db.scalar(
            select(Run)
            .join(Project)
            .where(Run.id == run_id)
            .where(Project.user_id == current_user.id)
        )
        if r is None or not r.screenshot_path:
            raise HTTPException(404, "no screenshot")
        ref = r.screenshot_path

    # R2: redirect to a (presigned/public) URL when available
    url = storage.artifact_url(ref)
    if url:
        return RedirectResponse(url)
    # otherwise stream the bytes (works for both local files and R2 fallback)
    data = storage.read_bytes(ref)
    if data is None:
        raise HTTPException(404, "screenshot missing")
    content, content_type = data
    return Response(content=content, media_type=content_type)


@router.get("/providers")
def supported_providers() -> list[str]:
    return sorted(PROVIDER_REGISTRY.keys())
