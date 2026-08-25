from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models._shared import utcnow


class WebhookEvent(SQLModel, table=True):
    """Append-only log of received Hunar webhooks — rows are never updated."""

    __tablename__ = "webhook_event"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_type: str
    call_id: str | None = Field(default=None, index=True)
    request_id: str | None = Field(default=None)
    signature_valid: bool
    raw_payload: dict[str, Any] = Field(sa_type=JSONB)
    received_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
