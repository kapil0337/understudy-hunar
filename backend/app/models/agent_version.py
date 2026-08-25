from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models._shared import pg_enum, utcnow
from app.models.enums import AgentVersionOrigin, Language, VoicePersona


class AgentVersion(SQLModel, table=True):
    __tablename__ = "agent_version"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "language", "version_no", name="uq_agent_version_job_language_version"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(foreign_key="job.id")
    version_no: int
    language: Language = Field(sa_column=Column(pg_enum(Language, "language_enum"), nullable=False))
    voice_persona: VoicePersona = Field(
        sa_column=Column(pg_enum(VoicePersona, "voice_persona_enum"), nullable=False)
    )
    persona_name: str
    agent_prompt: str = Field(sa_type=Text)
    objective: str = Field(sa_type=Text)
    introduction: str = Field(sa_type=Text)
    result_prompt: str = Field(sa_type=Text)
    result_schema: dict[str, Any] = Field(sa_type=JSONB)
    screening_questions: list[Any] = Field(default_factory=list, sa_type=JSONB)
    hunar_agent_id: str | None = Field(default=None)
    origin: AgentVersionOrigin = Field(
        sa_column=Column(pg_enum(AgentVersionOrigin, "agent_version_origin_enum"), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
