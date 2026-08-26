"""Request/response shapes for the /jobs and /versions routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentVersionOrigin, Language, VoicePersona


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
    draft AgentVersion row(s); it never edits an existing one (CONTRIBUTING.md: versions immutable)."""

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


class AgentVersionRead(BaseModel):
    """GET /versions/{id} — the version's full built prompt/schema, not just its identity
    (VersionSummary/VersionHistoryRow carry only the latter). Needed wherever a screen must
    show or diff against the exact text that was built for this version, e.g. the rehearsal
    screen's patch DiffView, which diffs the current agent_prompt against a proposed one."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    job_id: uuid.UUID
    version_no: int
    language: Language
    origin: AgentVersionOrigin
    voice_persona: VoicePersona
    persona_name: str
    agent_prompt: str
    objective: str
    introduction: str
    result_prompt: str
    result_schema: dict[str, Any]
    hunar_agent_id: str | None
    created_at: datetime


class RequirementsUpdateAccepted(BaseModel):
    """202 response for PUT /jobs/{id}/requirements: compiling a JD is an LLM call, deferred to
    app/worker.py. Poll GET /background-jobs/{id}; once COMPLETED, result.version_ids names the
    new draft AgentVersion(s) — fetch them via GET /jobs/{id}/versions."""

    model_config = ConfigDict(extra="forbid")

    background_job_id: uuid.UUID


class PersonaGenerationAccepted(BaseModel):
    """202 response for GET /jobs/{id}/personas when no personas exist yet for this job.
    Generating them is an LLM call, deferred to app/worker.py. Poll GET /background-jobs/{id},
    then re-GET this same endpoint once COMPLETED — it will return the generated list."""

    model_config = ConfigDict(extra="forbid")

    background_job_id: uuid.UUID


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
