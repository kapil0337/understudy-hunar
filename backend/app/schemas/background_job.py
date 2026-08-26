"""Request/response shapes for GET /background-jobs/{id} — the one generic poll target shared
by every LLM-heavy operation deferred to app/worker.py (compile_jd, regenerate_personas,
propose_patch, rehearse)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class BackgroundJobRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    kind: str
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
