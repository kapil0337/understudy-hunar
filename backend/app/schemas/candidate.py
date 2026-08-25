"""Request/response shapes for the candidate-sourcing and consent routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Language


class CandidateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    job_id: uuid.UUID
    source_provider: str
    source_ref: str
    full_name: str
    headline: str | None
    current_title: str | None
    current_company: str | None
    location: str | None
    skills: list[Any]
    years_experience: float | None
    linkedin_url: str | None
    phone_e164: str | None
    preferred_language: Language | None
    match_score: float | None
    match_breakdown: dict[str, Any] | None
    consent_recorded_at: datetime | None
    consent_channel: str | None
    dnc: bool


class CandidatePatch(BaseModel):
    """PATCH /candidates/{id} — phone, language, dnc, per the API surface. Every field is
    optional; only what is provided is changed."""

    model_config = ConfigDict(extra="forbid")

    phone_e164: str | None = None
    preferred_language: Language | None = None
    dnc: bool | None = None


class ConsentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_e164: str = Field(min_length=1)
    channel: str = "MANUAL"


class SourceRequest(BaseModel):
    """Body for POST /jobs/{id}/source. Every field optional — omitted fields fall back to the
    job's own compiled search_query, so 'source more like this' needs no body at all."""

    model_config = ConfigDict(extra="forbid")

    titles: list[str] | None = None
    skills: list[str] | None = None
    locations: list[str] | None = None
    min_years: float | None = None
    limit: int = Field(default=10, gt=0)


class SourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    cached: bool
    candidates: list[CandidateRead]


class CallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[uuid.UUID] = Field(min_length=1)
