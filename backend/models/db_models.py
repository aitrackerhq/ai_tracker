from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

"""
Application user profile.

Authentication is managed by Supabase Auth.
This table stores application-specific user information and owns projects.
"""

class Profile(Base):
    """
    Application user profile.

    Supabase Auth stores authentication.
    This table stores application-specific user data and
    owns projects.
    """

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    projects: Mapped[list["Project"]] = relationship(
        back_populates="owner"
    )

class Project(Base):
    """A tracked brand/site and its capture configuration."""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # Supabase user UUID that owns this project
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    geo_location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    providers: Mapped[str | None] = mapped_column(String(255), nullable=True)  # comma-separated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    prompts: Mapped[list["Prompt"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    runs: Mapped[list["Run"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    competitors: Mapped[list["Competitor"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    owner: Mapped["Profile | None"] = relationship(
        back_populates="projects"
    )

class Prompt(Base):
    """A search query belonging to a project."""
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="prompts")


class Run(Base):
    """One (provider, prompt) capture and its processing results."""
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geo_location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    processed_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    html_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_sentiment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_framing: Mapped[str | None] = mapped_column(String(32), nullable=True)
    framing_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="runs")
    mentions: Mapped[list["Mention"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    citations: Mapped[list["Citation"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Mention(Base):
    """A normalized brand/entity mention extracted from a run's response."""
    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_entity: Mapped[str] = mapped_column(String(255), nullable=False)
    mention_position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_target: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped["Run"] = relationship(back_populates="mentions")


class Citation(Base):
    """A source URL cited in a run's response."""
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    run: Mapped["Run"] = relationship(back_populates="citations")


class Competitor(Base):
    """A competitor brand for a project (explicit or LLM-inferred)."""
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    competitor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="competitors")


class SteelProfile(Base):
    """One persisted Steel browser profile per provider. Reusing a profile keeps
    Cloudflare clearance cookies + IP reputation across captures, so the
    challenge is cleared once then skipped — the free-tier reliability lever."""

    __tablename__ = "steel_profiles"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
