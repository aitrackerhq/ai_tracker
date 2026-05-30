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
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    geo_location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    providers: Mapped[str | None] = mapped_column(String(255), nullable=True)  # comma-separated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    prompts: Mapped[list["Prompt"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    runs: Mapped[list["Run"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    competitors: Mapped[list["Competitor"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="prompts")


class Run(Base):
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
    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_entity: Mapped[str] = mapped_column(String(255), nullable=False)
    mention_position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_target: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped["Run"] = relationship(back_populates="mentions")


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    run: Mapped["Run"] = relationship(back_populates="citations")


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    competitor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="competitors")
