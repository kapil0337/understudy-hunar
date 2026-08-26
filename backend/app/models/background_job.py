from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models._shared import utcnow


class BackgroundJob(SQLModel, table=True):
    """A queued unit of LLM-heavy work, claimed and executed by app/worker.py.

    Exists because these operations (compile_jd, regenerate_personas, propose_patch,
    rehearse) make several sequential LLM calls each and can run for minutes — too long to
    run inline in an HTTP request handler that might be served by a short-timeout serverless
    function. No new infra: this table IS the queue, polled with `FOR UPDATE SKIP LOCKED`
    (see app/worker.py) rather than via Redis/Celery, matching how the rest of this app already
    prefers Postgres-backed polling over webhooks (see RehearsalRun.status, refresh_outreach).

    `result` is a small kind-specific JSON payload rather than a single result_id column,
    because different kinds produce different shapes (compile_jd creates N versions, one per
    language; propose_patch creates one patch row) — see app/worker.py's handlers for exactly
    what each kind writes here.
    """

    __tablename__ = "background_job"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    kind: str
    payload: dict[str, Any] = Field(sa_type=JSONB)
    status: str = Field(default="PENDING")
    result: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    error: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    started_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
