from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    domain: str
    prompts: list[str] = Field(default_factory=list, max_length=5)
    competitors: list[str] = Field(default_factory=list)


class ProjectOut(BaseModel):
    id: int
    name: str
    domain: str
    prompts: list[str]
    competitors: list[str]
    created_at: str


class CaptureRequest(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["chatgpt", "gemini", "google_ai"])
    prompts: list[str] | None = None  # if None, uses project's saved prompts
