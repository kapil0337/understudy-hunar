from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models._shared import utcnow


class LLMCache(SQLModel, table=True):
    """Keyed by sha256(role, model, messages, schema) — see CLAUDE.md. Caching here is what
    makes iterating on the rehearsal loop affordable, not an optimisation."""

    __tablename__ = "llm_cache"

    key: str = Field(primary_key=True)
    role: str
    model: str
    response: dict[str, Any] = Field(sa_type=JSONB)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class ProviderCache(SQLModel, table=True):
    __tablename__ = "provider_cache"

    key: str = Field(primary_key=True)
    provider: str
    response: dict[str, Any] = Field(sa_type=JSONB)
    fetched_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
