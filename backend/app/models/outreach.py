from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models._shared import pg_enum, utcnow
from app.models.enums import CallStatus

# f"{job_short}-{candidate_short}-a{attempt}" — the correlation key between our DB and Hunar.
_REQUEST_ID_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"


class Outreach(SQLModel, table=True):
    __tablename__ = "outreach"
    __table_args__ = (
        CheckConstraint(
            f"request_id ~ '{_REQUEST_ID_PATTERN}'", name="ck_outreach_request_id_format"
        ),
        Index("ix_outreach_result_gin", "result", postgresql_using="gin"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(foreign_key="candidate.id")
    agent_version_id: uuid.UUID = Field(foreign_key="agent_version.id")
    hunar_call_id: str | None = Field(default=None, index=True)
    request_id: str = Field(unique=True, max_length=64)
    status: CallStatus = Field(
        default=CallStatus.NOT_STARTED,
        sa_column=Column(pg_enum(CallStatus, "call_status_enum"), nullable=False),
    )
    lifecycle_status: str
    answered_by: str | None = Field(default=None)
    engagement_status: str | None = Field(default=None)
    duration_seconds: int | None = Field(default=None)
    recording_url: str | None = Field(default=None)
    result: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    call_summary: str | None = Field(default=None, sa_type=Text)
    is_simulated: bool = Field(default=False)
    error_message: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=utcnow),
    )
