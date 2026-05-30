from __future__ import annotations

from pydantic import BaseModel, Field


DEFAULT_PROVIDERS = ["chatgpt", "gemini", "perplexity", "google_ai", "google_ai_mode"]


class ProjectCreate(BaseModel):
    name: str
    domain: str
    prompts: list[str] = Field(default_factory=list, max_length=5)
    competitors: list[str] = Field(default_factory=list)
    geo_location: str | None = None
    providers: list[str] = Field(default_factory=lambda: list(DEFAULT_PROVIDERS))


class ProjectOut(BaseModel):
    id: int
    name: str
    domain: str
    prompts: list[str]
    competitors: list[str]
    geo_location: str | None = None
    providers: list[str] = Field(default_factory=list)
    created_at: str


class SuggestPromptsBody(BaseModel):
    domain: str
    competitors: list[str] = Field(default_factory=list)
    existing_prompts: list[str] = Field(default_factory=list)


class CaptureRequest(BaseModel):
    providers: list[str] = Field(
        default_factory=lambda: ["chatgpt", "gemini", "perplexity", "google_ai", "google_ai_mode"]
    )
    prompts: list[str] | None = None  # if None, uses project's saved prompts
    geo_location: str | None = None  # overrides the project's default geo
    force_refresh: bool = False  # bypass the result cache
