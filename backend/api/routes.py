from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from backend.analytics import AnalyticsService
from backend.api.schemas import CaptureRequest, ProjectCreate, ProjectOut
from backend.capture import create_pending_runs, run_capture
from backend.database.session import session_scope
from backend.models import Competitor, Project, Prompt
from backend.processing.pipeline import process_project
from backend.providers import PROVIDER_REGISTRY

router = APIRouter(prefix="/api")


# ---------- projects ----------

@router.post("/projects", response_model=ProjectOut)
def create_project(payload: ProjectCreate) -> ProjectOut:
    if not payload.name or not payload.domain:
        raise HTTPException(400, "name and domain are required")
    with session_scope() as db:
        proj = Project(name=payload.name.strip(), domain=payload.domain.strip().lower())
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


@router.get("/projects", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    with session_scope() as db:
        projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
        return [_project_to_out(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int) -> ProjectOut:
    with session_scope() as db:
        proj = db.get(Project, project_id)
        if proj is None:
            raise HTTPException(404, "project not found")
        return _project_to_out(proj)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int) -> dict:
    with session_scope() as db:
        proj = db.get(Project, project_id)
        if proj is None:
            raise HTTPException(404, "project not found")
        db.delete(proj)
    return {"ok": True}


def _project_to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        domain=p.domain,
        prompts=[pr.prompt_text for pr in p.prompts],
        competitors=[c.competitor_name for c in p.competitors],
        created_at=p.created_at.isoformat() + "Z",
    )


# ---------- capture ----------

@router.post("/projects/{project_id}/capture")
def trigger_capture(
    project_id: int,
    payload: CaptureRequest,
    bg: BackgroundTasks,
) -> dict:
    with session_scope() as db:
        proj = db.get(Project, project_id)
        if proj is None:
            raise HTTPException(404, "project not found")
        prompts = payload.prompts or [p.prompt_text for p in proj.prompts]

    if not prompts:
        raise HTTPException(400, "no prompts to run")

    unknown = [p for p in payload.providers if p not in PROVIDER_REGISTRY]
    if unknown:
        raise HTTPException(400, f"unknown providers: {unknown}")

    # Pre-create all (provider × prompt) runs as "pending" so the dashboard can
    # render the full pipeline immediately, then run them in the background.
    batch_id, run_ids = create_pending_runs(project_id, prompts, payload.providers)
    bg.add_task(run_capture, run_ids)
    return {
        "ok": True,
        "batch_id": batch_id,
        "run_ids": run_ids,
        "providers": payload.providers,
        "prompts": len(prompts),
    }


@router.post("/projects/{project_id}/reprocess")
def reprocess(project_id: int) -> dict:
    count = process_project(project_id)
    return {"ok": True, "reprocessed": count}


# ---------- analytics ----------

@router.get("/projects/{project_id}/overview")
def overview(project_id: int) -> dict:
    data = AnalyticsService.overview(project_id)
    if not data:
        raise HTTPException(404, "project not found")
    return data


@router.get("/projects/{project_id}/runs")
def runs(project_id: int) -> list[dict]:
    return AnalyticsService.runs(project_id)


@router.get("/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    data = AnalyticsService.run_detail(run_id)
    if data is None:
        raise HTTPException(404, "run not found")
    return data


@router.get("/projects/{project_id}/competitors")
def competitors(project_id: int) -> dict:
    return AnalyticsService.competitors(project_id)


@router.get("/projects/{project_id}/providers")
def provider_comparison(project_id: int) -> dict:
    return AnalyticsService.provider_comparison(project_id)


@router.get("/projects/{project_id}/timeseries")
def timeseries(project_id: int) -> dict:
    return AnalyticsService.timeseries(project_id)


@router.get("/projects/{project_id}/history")
def history(project_id: int) -> dict:
    return AnalyticsService.history(project_id)


# ---------- artifacts ----------

@router.get("/artifacts/screenshot/{run_id}")
def get_screenshot(run_id: int):
    with session_scope() as db:
        from backend.models import Run

        r = db.get(Run, run_id)
        if r is None or not r.screenshot_path:
            raise HTTPException(404, "no screenshot")
        p = Path(r.screenshot_path)
        if not p.exists():
            raise HTTPException(404, "screenshot missing")
        return FileResponse(p, media_type="image/png")


@router.get("/providers")
def supported_providers() -> list[str]:
    return sorted(PROVIDER_REGISTRY.keys())
