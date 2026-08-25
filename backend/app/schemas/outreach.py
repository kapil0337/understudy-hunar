"""Output shapes for app/services/outreach.py."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class BlockedCandidate(BaseModel):
    """One candidate call_candidates refused to dial, and why. Recruiters must see this list —
    per CLAUDE.md the guard is unbypassable, so a skip is never silent."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: uuid.UUID
    reason: str


class QueuedCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: uuid.UUID
    outreach_id: uuid.UUID
    request_id: str
    hunar_call_id: str


class CallLaunchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queued: list[QueuedCall]
    blocked: list[BlockedCandidate]
    versions_used: dict[str, uuid.UUID]  # language value -> agent_version id
    estimated_minutes: float
