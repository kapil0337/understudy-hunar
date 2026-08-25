"""PDL-specific HTTP failure modes, distinct so the sourcing service can tell "bad key" and
"out of credits" (both: fall back to fixtures) apart from a genuine 5xx (retried first)."""

from __future__ import annotations

from typing import Any

from app.integrations.sourcing.base import (
    SourcingAuthError,
    SourcingProviderError,
    SourcingQuotaExceeded,
)


class PDLAPIError(SourcingProviderError):
    """An HTTP error response from PDL. Carries the raw body so an unexpected shape is still
    inspectable rather than lost."""

    default_message = "PDL API request failed"

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


class PDLUnauthorized(PDLAPIError, SourcingAuthError):
    """401/403 — missing or invalid X-Api-Key."""

    default_message = "PDL rejected the API key"


class PDLQuotaExceeded(PDLAPIError, SourcingQuotaExceeded):
    """402/429 — out of monthly credits or over the 10 req/min rate limit."""

    default_message = "PDL credits exhausted or rate limited"


#: Maps HTTP status to the exception raised for it. Anything absent falls back to PDLAPIError.
STATUS_EXCEPTIONS: dict[int, type[PDLAPIError]] = {
    401: PDLUnauthorized,
    402: PDLQuotaExceeded,
    403: PDLUnauthorized,
    429: PDLQuotaExceeded,
}
