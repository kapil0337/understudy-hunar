from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Persona(SQLModel, table=True):
    __tablename__ = "persona"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(foreign_key="job.id")
    archetype: str
    profile: dict[str, Any] = Field(sa_type=JSONB)
    ground_truth: dict[str, Any] = Field(sa_type=JSONB)
    behaviour: dict[str, Any] = Field(sa_type=JSONB)
