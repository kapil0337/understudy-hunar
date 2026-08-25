"""Response shape for GET /jobs/{id}/board."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class BoardRow(BaseModel):
    """One candidate plus their latest outreach attempt, if any. Fields from Outreach are None
    when the candidate has never been called."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: uuid.UUID
    full_name: str
    match_score: float | None
    phone_e164: str | None
    consent_recorded_at: datetime | None
    dnc: bool

    outreach_id: uuid.UUID | None
    agent_version_id: uuid.UUID | None
    status: str | None
    lifecycle_status: str | None
    duration_seconds: int | None
    recording_url: str | None
    result: dict[str, Any] | None
    call_summary: str | None
    is_simulated: bool


class BoardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: uuid.UUID
    rows: list[BoardRow]
