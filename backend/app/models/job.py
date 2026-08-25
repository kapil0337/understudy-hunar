from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models._shared import utcnow


class Job(SQLModel, table=True):
    __tablename__ = "job"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str
    raw_jd: str = Field(sa_type=Text)
    compiled: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
