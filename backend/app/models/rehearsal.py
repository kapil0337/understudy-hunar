from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models._shared import utcnow


class RehearsalRun(SQLModel, table=True):
    __tablename__ = "rehearsal_run"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_version_id: uuid.UUID = Field(foreign_key="agent_version.id")
    status: str
    scores: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    llm_calls: int = Field(default=0)
    cached_calls: int = Field(default=0)
    started_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    error: str | None = Field(default=None, sa_type=Text)


class RehearsalCase(SQLModel, table=True):
    __tablename__ = "rehearsal_case"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="rehearsal_run.id", index=True)
    persona_id: uuid.UUID = Field(foreign_key="persona.id")
    # Lists, not dicts: transcript is [{speaker, text, turn}, ...] and failures is a list of
    # per-metric failure records (see app/services/rehearsal/score.py). JSONB is untyped at the
    # DB level so this is a pure Python-side annotation fix — no migration needed.
    transcript: list[Any] | None = Field(default=None, sa_type=JSONB)
    extracted_result: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    metrics: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    failures: list[Any] | None = Field(default=None, sa_type=JSONB)
    estimated_seconds: float | None = Field(default=None)
    turn_count: int | None = Field(default=None)


class PromptPatch(SQLModel, table=True):
    __tablename__ = "prompt_patch"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="rehearsal_run.id")
    proposed_agent_prompt: str = Field(sa_type=Text)
    # A list of {failure_id, change_summary, quoted_new_text} — see
    # app/services/rehearsal/patch.py. Same JSONB Python-side annotation fix as transcript/
    # failures above.
    rationale: list[Any] = Field(sa_type=JSONB)
    accepted: bool = Field(default=False)
    resulting_version_id: uuid.UUID | None = Field(default=None, foreign_key="agent_version.id")
