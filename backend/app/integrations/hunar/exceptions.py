"""Distinct exception per documented Hunar failure mode.

These exist so callers can react differently to "your key is wrong" versus "you are out of
calling minutes" versus "this number cannot be dialled". Collapsing them into one error type
is what turns a 402 into an opaque 500 for the operator.
"""

from __future__ import annotations

from typing import Any


class HunarAdapterError(Exception):
    """Base for every Hunar adapter failure.

    Named to stay out of the way of models.HunarError, which is the {success, message, details}
    response envelope rather than an exception.
    """


class HunarAPIError(HunarAdapterError):
    """An HTTP error response from Hunar.

    Carries the parsed {success, message, details} envelope when there was one, plus the raw
    body so an unexpected shape is still inspectable rather than lost.
    """

    #: Human-facing summary. Subclasses override where the API's own message is too vague to
    #: show an operator directly.
    default_message = "Hunar API request failed"

    def __init__(
        self,
        status_code: int,
        *,
        message: str | None = None,
        details: Any = None,
        raw_body: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.details = details
        self.raw_body = raw_body
        super().__init__(f"{self.default_message} (HTTP {status_code}): {message or raw_body!r}")

    @property
    def operator_message(self) -> str:
        """What to show a human. Falls back to the API's message when there is no better one."""
        return self.message or self.default_message


class HunarUnauthorized(HunarAPIError):
    """401 — missing or invalid X-API-Key."""

    default_message = "Hunar rejected the API key"


class HunarQuotaExhausted(HunarAPIError):
    """402 — out of calling minutes.

    Deliberately its own type: this is an expected, actionable operational state, not a bug.
    It must reach the operator as "calling minutes exhausted", never as a generic 500.
    """

    default_message = "Calling minutes exhausted"

    @property
    def operator_message(self) -> str:
        # Ignore the API's wording here — this specific phrasing is what the operator needs to
        # see, and it must not be diluted by whatever the server happened to send.
        return "Calling minutes exhausted"


class HunarNotFound(HunarAPIError):
    """404 — no such agent/call/number."""

    default_message = "Hunar resource not found"


class HunarValidationError(HunarAPIError):
    """422 — request rejected.

    Most causes are catchable locally first; see preflight.py.
    """

    default_message = "Hunar rejected the request payload"


class HunarTelephonyError(HunarAPIError):
    """400 — telephony-level rejection (bad number, disallowed destination, no route)."""

    default_message = "Hunar could not place the call"


#: Maps HTTP status to the exception raised for it. Anything absent falls back to
#: HunarAPIError, so a new documented status never silently becomes a success.
STATUS_EXCEPTIONS: dict[int, type[HunarAPIError]] = {
    400: HunarTelephonyError,
    401: HunarUnauthorized,
    402: HunarQuotaExhausted,
    404: HunarNotFound,
    422: HunarValidationError,
}
