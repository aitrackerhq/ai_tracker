"""Seed an example project + one synthetic run so the dashboard has data to render
without needing a live browser. Useful for smoke-testing the frontend.
"""
from __future__ import annotations

import json
from datetime import datetime

from backend.database.session import engine, session_scope
from backend.models import Base, Citation, Competitor, Mention, Project, Prompt, Run
from backend.processing.pipeline import process_run
from backend.storage import raw_store
from backend.utils.helpers import new_run_id


EXAMPLE_RESPONSE = """Here are the best project management tools for startups in 2026:

1. **Notion** — flexible workspace combining docs, wikis, and lightweight project tracking. Best for documentation-heavy teams.
2. **ClickUp** — most feature-rich; works well for engineering teams that want one tool for tasks, sprints, and docs.
3. **Linear** — minimalist issue tracker beloved by product engineering teams.
4. **Asana** — strong for cross-functional project planning.
5. **Confluence** — Atlassian's knowledge base, common in enterprise teams using Jira.

For a documentation-first workspace, Notion remains the most popular default among modern startups."""


EXAMPLE_CITATIONS = [
    {"title": "Notion", "url": "https://www.notion.so/product", "domain": "notion.so"},
    {"title": "ClickUp", "url": "https://clickup.com/", "domain": "clickup.com"},
    {"title": "Linear", "url": "https://linear.app/", "domain": "linear.app"},
]


def seed() -> int:
    Base.metadata.create_all(bind=engine)
    with session_scope() as db:
        proj = Project(name="Notion", domain="notion.so")
        db.add(proj)
        db.flush()
        for p in [
            "best project management software for startups",
            "best collaboration tools",
            "alternatives to confluence",
        ]:
            db.add(Prompt(project_id=proj.id, prompt_text=p))
        for c in ["ClickUp", "Confluence", "Linear"]:
            db.add(Competitor(project_id=proj.id, competitor_name=c, inferred=False))
        db.flush()
        project_id = proj.id

    # synthetic run across three providers
    run_pks: list[int] = []
    for provider in ("chatgpt", "gemini", "google_ai"):
        run_uid = new_run_id()
        payload = {
            "provider": provider,
            "prompt": "best project management software for startups",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "response_text": EXAMPLE_RESPONSE,
            "citations": EXAMPLE_CITATIONS,
            "links": [],
            "metadata": {"response_time": 8.4, "has_citations": True, "synthetic": True},
            "screenshot_path": None,
            "html_path": None,
            "has_ai_overview": True if provider == "google_ai" else None,
        }
        raw_store.write(run_uid, payload)
        with session_scope() as db:
            r = Run(
                project_id=project_id,
                provider=provider,
                prompt=payload["prompt"],
                raw_json_path=str(raw_store.path_for(run_uid)),
                status="captured",
            )
            db.add(r)
            db.flush()
            run_pks.append(r.id)

    for rid in run_pks:
        process_run(rid)

    print(f"seeded project_id={project_id}, runs={run_pks}")
    return project_id


if __name__ == "__main__":
    seed()
