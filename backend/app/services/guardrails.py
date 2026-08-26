"""The org-wide calling policy: allowed days/hours and retry behaviour for every outbound call.

publish_version previously omitted guardrails/retry_config entirely, which per CLAUDE.md means
"inherit org defaults" — but Hunar's own agent-detail response never echoes those back (see
tests/fixtures/hunar/agent_detail.json, a real scrubbed capture with neither field present), so
there was no way to answer "what's our calling window right now" from anything Hunar returns.
Sending an explicit, known policy on every publish — and treating this module as its one source
of truth — replaces "inherited and opaque" with "set by us and readable by us." IST is a fixed
UTC+05:30 offset with no DST, so the window check below needs no tzdata/zoneinfo dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.integrations.hunar.models import WEEKDAYS, Guardrails, RetryConfig

TIMEZONE = "Asia/Kolkata"

GUARDRAILS = Guardrails(
    allowed_days=["MON", "TUE", "WED", "THU", "FRI"],
    earliest_call_time="10:00",
    last_call_time="18:00",
)
RETRY_CONFIG = RetryConfig(max_retry_count=2, retry_interval_hours=6)

_IST_OFFSET = timedelta(hours=5, minutes=30)


def is_within_calling_window(now: datetime | None = None) -> bool:
    moment = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    shifted = moment + _IST_OFFSET  # naive clock-time shift; IST has no DST to account for

    # weekday() is Monday=0..Sunday=6, matching WEEKDAYS' order — avoids locale-dependent
    # strftime("%A") output.
    if WEEKDAYS[shifted.weekday()] not in GUARDRAILS.allowed_days:
        return False
    current_time = shifted.strftime("%H:%M")
    return GUARDRAILS.earliest_call_time <= current_time <= GUARDRAILS.last_call_time
