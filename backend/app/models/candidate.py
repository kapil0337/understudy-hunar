from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models._shared import pg_enum
from app.models.enums import Language


class Candidate(SQLModel, table=True):
    __tablename__ = "candidate"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(foreign_key="job.id")
    source_provider: str
    source_ref: str
    full_name: str
    headline: str | None = Field(default=None)
    current_title: str | None = Field(default=None)
    current_company: str | None = Field(default=None)
    location: str | None = Field(default=None)
    skills: list[Any] = Field(default_factory=list, sa_type=JSONB)
    years_experience: float | None = Field(default=None)
    linkedin_url: str | None = Field(default=None)
    phone_e164: str | None = Field(default=None)
    preferred_language: Language | None = Field(
        default=None, sa_column=Column(pg_enum(Language, "language_enum"), nullable=True)
    )
    match_score: float | None = Field(default=None)
    match_breakdown: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    consent_recorded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    consent_channel: str | None = Field(default=None)
    dnc: bool = Field(default=False)
    raw_payload: dict[str, Any] = Field(sa_type=JSONB)
