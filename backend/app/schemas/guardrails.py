"""Response shape for GET /guardrails."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.integrations.hunar.models import RetryIntervalHours, Weekday


class GuardrailsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_days: list[Weekday]
    earliest_call_time: str
    last_call_time: str
    timezone: str
    max_retry_count: int
    retry_interval_hours: RetryIntervalHours
    inside_window_now: bool
