"""Local validators that run BEFORE any Hunar API call.

Every check here mirrors a documented server-side rejection. Catching them locally turns an
opaque remote 422 into a specific, actionable message, and avoids spending a request (and, for
calls, risking a partial side effect) to learn something we already knew.

Raises PreflightError, which is deliberately NOT a HunarAPIError: nothing was sent, so this is
not an API failure.
"""

from __future__ import annotations

import phonenumbers

from app.integrations.hunar.exceptions import HunarAdapterError
from app.integrations.hunar.models import (
    WEEKDAYS,
    Agent,
    Guardrails,
    PhoneNumber,
    RetryConfig,
)

MIN_DISTINCT_ALLOWED_DAYS = 3
MIN_GUARDRAIL_WINDOW_MINUTES = 3 * 60
VALID_RETRY_INTERVALS = frozenset({0, 3, 6, 9, 12, 24})


class PreflightError(HunarAdapterError):
    """A request was rejected locally, before reaching Hunar."""


def check_custom_data(agent: Agent, custom_data: dict[str, object]) -> None:
    """custom_data must contain EVERY key in the agent's custom_variables, else Hunar 422s."""
    required = set(agent.custom_variables)
    if not required:
        return

    missing = sorted(required - set(custom_data))
    if missing:
        raise PreflightError(
            f"custom_data is missing {len(missing)} key(s) required by agent {agent.id}: "
            f"{', '.join(missing)}. Every key in the agent's custom_variables must be present."
        )


def check_retry_config(retry_config: RetryConfig | None) -> None:
    """retry_config must be complete or absent — a partial object is a 422.

    Completeness is already structural (both fields are required on the model), so what is
    left to check is the value domain of retry_interval_hours, which Pydantic's Literal
    catches at construction but which is re-checked here for configs built dynamically.
    """
    if retry_config is None:
        return

    if not 0 <= retry_config.max_retry_count <= 10:
        raise PreflightError(
            f"retry_config.max_retry_count must be between 0 and 10, "
            f"got {retry_config.max_retry_count}."
        )

    if retry_config.retry_interval_hours not in VALID_RETRY_INTERVALS:
        allowed = ", ".join(str(value) for value in sorted(VALID_RETRY_INTERVALS))
        raise PreflightError(
            f"retry_config.retry_interval_hours must be one of {allowed}, "
            f"got {retry_config.retry_interval_hours}."
        )


def check_guardrails(guardrails: Guardrails | None) -> None:
    """guardrails must be complete or absent (absent inherits org defaults).

    Requires at least 3 distinct allowed days and a calling window of at least 3 hours.
    """
    if guardrails is None:
        return

    distinct_days = set(guardrails.allowed_days)
    unknown = sorted(distinct_days - set(WEEKDAYS))
    if unknown:
        raise PreflightError(
            f"guardrails.allowed_days contains unknown day(s): {', '.join(unknown)}."
        )

    if len(distinct_days) < MIN_DISTINCT_ALLOWED_DAYS:
        raise PreflightError(
            f"guardrails.allowed_days needs at least {MIN_DISTINCT_ALLOWED_DAYS} distinct days, "
            f"got {len(distinct_days)}."
        )

    earliest = _parse_hhmm(guardrails.earliest_call_time, "earliest_call_time")
    latest = _parse_hhmm(guardrails.last_call_time, "last_call_time")

    window = latest - earliest
    if window < MIN_GUARDRAIL_WINDOW_MINUTES:
        raise PreflightError(
            f"guardrails calling window must be at least 3 hours; "
            f"{guardrails.earliest_call_time}–{guardrails.last_call_time} is "
            f"{window // 60}h{window % 60:02d}m."
        )


def check_mobile_number(mobile_number: str) -> phonenumbers.PhoneNumber:
    """The number must parse as E.164 and be a valid, dialable number."""
    if not mobile_number.startswith("+"):
        raise PreflightError(
            f"mobile_number must be E.164 and start with '+', got {mobile_number!r}."
        )

    try:
        parsed = phonenumbers.parse(mobile_number, None)
    except phonenumbers.NumberParseException as exc:
        raise PreflightError(f"mobile_number {mobile_number!r} is not parseable: {exc}") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise PreflightError(f"mobile_number {mobile_number!r} is not a valid phone number.")

    return parsed


def check_destination_allowed(mobile_number: str, number: PhoneNumber) -> None:
    """The destination country must appear in the originating number's allowed_countries."""
    parsed = check_mobile_number(mobile_number)
    destination = phonenumbers.region_code_for_number(parsed)

    if destination is None:
        raise PreflightError(
            f"Could not determine a destination country for mobile_number {mobile_number!r}."
        )

    if not number.allowed_countries:
        raise PreflightError(
            f"Hunar number {number.id} reports no allowed_countries, so no destination can be "
            "verified as permitted. Refusing to place the call."
        )

    allowed = {country.upper() for country in number.allowed_countries}
    if destination.upper() not in allowed:
        raise PreflightError(
            f"Destination {destination} is not in the allowed_countries for Hunar number "
            f"{number.id} ({', '.join(sorted(allowed))})."
        )


def _parse_hhmm(value: str, field: str) -> int:
    """Return minutes since midnight for an HH:MM string."""
    try:
        hours_text, minutes_text = value.split(":")
        hours, minutes = int(hours_text), int(minutes_text)
    except (AttributeError, ValueError) as exc:
        raise PreflightError(f"guardrails.{field} must be HH:MM, got {value!r}.") from exc

    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise PreflightError(f"guardrails.{field} must be a valid HH:MM time, got {value!r}.")

    return hours * 60 + minutes
