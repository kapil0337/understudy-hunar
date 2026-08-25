"""Request/response shapes for the /jobs and /versions routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentVersionOrigin, Language


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    raw_jd: str = Field(min_length=1)


class JobRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    title: str
    raw_jd: str
    compiled: dict[str, Any] | None
    created_at: datetime


class RequirementsUpdate(BaseModel):
    """Body for PUT /jobs/{id}/requirements — a revised raw JD. Recompiling always creates new
    draft AgentVersion row(s); it never edits an existing one (CLAUDE.md: versions immutable)."""

    model_config = ConfigDict(extra="forbid")

    raw_jd: str = Field(min_length=1)


class VersionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    job_id: uuid.UUID
    version_no: int
    language: Language
    origin: AgentVersionOrigin
    hunar_agent_id: str | None


class RequirementsUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: uuid.UUID
    versions: list[VersionSummary]


class VersionHistoryRow(BaseModel):
    """One row of GET /jobs/{id}/versions: a version plus its most recent rehearsal composite,
    if it has been rehearsed at all."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    version_no: int
    language: Language
    origin: AgentVersionOrigin
    hunar_agent_id: str | None
    latest_composite_score: float | None


class PersonaRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    archetype: str
    profile: dict[str, Any]
    ground_truth: dict[str, Any]
    behaviour: dict[str, Any]
