"""Response shape for GET /debug/webhooks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class WebhookEventRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    event_type: str
    call_id: str | None
    request_id: str | None
    signature_valid: bool
    raw_payload: dict[str, Any]
    received_at: datetime
