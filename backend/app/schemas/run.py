"""Request/response shapes for the /runs and /patches routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.job import VersionSummary


class RehearseAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    status: str


class CaseSummary(BaseModel):
    """One row of RunRead.case_summaries — enough to pick a case to drill into, not the full
    transcript (see GET /runs/{id}/cases/{case_id} for that)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    persona_id: uuid.UUID
    archetype: str
    turn_count: int | None
    estimated_seconds: float | None


class RunRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    agent_version_id: uuid.UUID
    status: str
    scores: dict[str, Any] | None
    llm_calls: int
    cached_calls: int
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    case_summaries: list[CaseSummary]


class CaseRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    run_id: uuid.UUID
    persona_id: uuid.UUID
    archetype: str
    transcript: list[Any] | None
    extracted_result: dict[str, Any] | None
    ground_truth: dict[str, Any]
    metrics: dict[str, Any] | None
    failures: list[Any] | None


class PatchRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    run_id: uuid.UUID
    proposed_agent_prompt: str
    rationale: list[Any]
    accepted: bool
    resulting_version_id: uuid.UUID | None


class PatchAcceptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: VersionSummary
    run: RunRead
    score_delta: dict[str, float]
