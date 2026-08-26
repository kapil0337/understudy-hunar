"""Coresignal Multi-source Employee API provider.

Two-step, unlike PDL's single-call search: POST .../search/es_dsl returns a bare JSON array of
employee ids (no full records), then each id must be fetched individually via
GET .../collect/{id} for a full record. Collect costs API credits per profile; search does not
— so MAX_RESULTS_PER_SEARCH is kept deliberately small regardless of what SourcingQuery.limit
asks for, unlike PDL where a bigger free-tier search is one call.

Coresignal's docs do not publish example request/response bodies for this endpoint, so the
shapes below were verified live against the real API (2026-08-26) rather than guessed at, per
CLAUDE.md's "never invent fields":
  - search response: a bare JSON array of integer ids, e.g. [123, 456, ...]. A raw `{"size": N}`
    sibling key is rejected with `extra_forbidden`, so result count is controlled client-side by
    truncating the id list, not via the request body.
  - collect response: a flat object; no field anywhere reports a phone number (same as PDL —
    see app/integrations/sourcing/base.py's module docstring on why phone_e164 is never set
    here regardless of provider).
  - error envelope on 401/429: {"message": str, "request_id": str}.
  - rate limit: 5 requests/second, applying to both search and collect calls.
"""

from __future__ import annotations

import json
from types import TracebackType
from typing import Any, Self

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import WaitBaseT

from app.integrations.sourcing.base import (
    SourcedCandidate,
    SourcingAuthError,
    SourcingProviderError,
    SourcingQuery,
    SourcingQuotaExceeded,
    SourcingResult,
)
from app.integrations.sourcing.ratelimit import TokenBucket

logger = structlog.get_logger()

BASE_URL = "https://api.coresignal.com/cdapi/v2"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_ATTEMPTS = 3

#: Collect costs credits per profile (search does not) — kept small regardless of what the
#: caller's SourcingQuery.limit asks for, so one search cannot burn a trial's whole allowance.
MAX_RESULTS_PER_SEARCH = 5
#: Verified live via response headers (`ratelimit-limit: 5`) and a real 429.
RATE_LIMIT_REQUESTS = 5
RATE_LIMIT_PERIOD_SECONDS = 1.0

_RETRYABLE_TRANSPORT = (httpx.TimeoutException, httpx.TransportError)


class CoresignalAPIError(SourcingProviderError):
    """An HTTP error response from Coresignal. Carries the raw body so an unexpected shape is
    still inspectable rather than lost."""

    default_message = "Coresignal API request failed"

    def __init__(
        self,
        status_code: int,
        *,
        message: str | None = None,
        raw_body: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.raw_body = raw_body
        super().__init__(f"{self.default_message} (HTTP {status_code}): {message or raw_body!r}")


class CoresignalUnauthorized(CoresignalAPIError, SourcingAuthError):
    """401/403 — missing or invalid apikey header."""

    default_message = "Coresignal rejected the API key"


class CoresignalQuotaExceeded(CoresignalAPIError, SourcingQuotaExceeded):
    """402/429 — out of credits, or over the 5 requests/second rate limit."""

    default_message = "Coresignal credits exhausted or rate limited"


#: Maps HTTP status to the exception raised for it. Anything absent falls back to
#: CoresignalAPIError. Mirrors app/integrations/sourcing/exceptions.py's PDL table.
STATUS_EXCEPTIONS: dict[int, type[CoresignalAPIError]] = {
    401: CoresignalUnauthorized,
    402: CoresignalQuotaExceeded,
    403: CoresignalUnauthorized,
    429: CoresignalQuotaExceeded,
}


class _Retryable(Exception):
    """Internal marker for a 5xx worth retrying; never escapes a public method."""

    def __init__(self, original: CoresignalAPIError) -> None:
        self.original = original
        super().__init__(str(original))


def build_search_query(query: SourcingQuery) -> dict[str, Any]:
    """Elasticsearch DSL `query` object — the ONLY top-level key Coresignal's schema accepts
    (verified live: a sibling `size` is rejected). Multiple values within one dimension are
    OR'd (bool.should); the dimensions themselves are AND'd (bool.must), same shape as PDL's
    build_search_body."""
    must: list[dict[str, Any]] = []
    if query.titles:
        must.append(
            {"bool": {"should": [{"match": {"active_experience_title": t}} for t in query.titles]}}
        )
    if query.skills:
        must.append({"bool": {"should": [{"match": {"inferred_skills": s}} for s in query.skills]}})
    if query.locations:
        must.append(
            {"bool": {"should": [{"match": {"location_full": loc}} for loc in query.locations]}}
        )
    if query.min_years is not None:
        must.append({"range": {"total_experience_duration_months": {"gte": query.min_years * 12}}})

    es_query: dict[str, Any] = {"bool": {"must": must}} if must else {"match_all": {}}
    return {"query": es_query}


class _CoresignalExperience(BaseModel):
    model_config = ConfigDict(extra="allow")

    active_experience: int | None = None
    company_name: str | None = None


class _CoresignalEmployee(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    full_name: str | None = None
    headline: str | None = None
    active_experience_title: str | None = None
    location_full: str | None = None
    inferred_skills: list[str] | None = None
    total_experience_duration_months: float | None = None
    linkedin_url: str | None = None
    experience: list[_CoresignalExperience] | None = None


def _current_company(employee: _CoresignalEmployee) -> str | None:
    """The employer of the entry flagged active_experience == 1 — not necessarily experience[0]
    (verified live: it happened to be first in the one record inspected, but nothing documents
    that ordering, so this searches rather than assumes)."""
    for entry in employee.experience or []:
        if entry.active_experience == 1:
            return entry.company_name
    return None


def _to_sourced_candidate(employee: _CoresignalEmployee) -> SourcedCandidate:
    return SourcedCandidate(
        source_ref=(
            str(employee.id) if employee.id is not None else (employee.full_name or "unknown")
        ),
        full_name=employee.full_name or "Unknown",
        headline=employee.headline,
        current_title=employee.active_experience_title,
        current_company=_current_company(employee),
        location=employee.location_full,
        skills=employee.inferred_skills or [],
        years_experience=(
            employee.total_experience_duration_months / 12.0
            if employee.total_experience_duration_months is not None
            else None
        ),
        linkedin_url=employee.linkedin_url,
        preferred_language=None,  # Not reported by this API; never guessed at.
        has_phone_flag=False,  # No field in this API ever reports phone presence.
        needs_phone=True,
        raw=employee.model_dump(mode="json"),
    )


class CoresignalProvider:
    name = "coresignal"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_wait: WaitBaseT | None = None,
        rate_limiter: TokenBucket | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Coresignal api_key must not be empty")

        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts
        self._retry_wait: WaitBaseT = retry_wait or wait_exponential(multiplier=0.5, min=0.5, max=8)
        self._rate_limiter = rate_limiter or TokenBucket(
            RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD_SECONDS
        )
        self._headers = {"apikey": api_key, "Accept": "application/json"}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, query: SourcingQuery) -> SourcingResult:
        body = build_search_query(query)
        ids = await self._request("POST", "/employee_multi_source/search/es_dsl", json=body)
        if not isinstance(ids, list):
            logger.error("coresignal_unexpected_search_shape", raw=ids)
            raise SourcingProviderError(f"Coresignal search did not return a list of ids: {ids!r}")

        limit = min(query.limit, MAX_RESULTS_PER_SEARCH)
        candidates = [
            _to_sourced_candidate(await self._collect(employee_id)) for employee_id in ids[:limit]
        ]
        return SourcingResult(provider=self.name, candidates=candidates, cached=False)

    # ---------------------------------------------------------------- internals

    async def _collect(self, employee_id: Any) -> _CoresignalEmployee:
        payload = await self._request(
            "GET", f"/employee_multi_source/collect/{employee_id}", json=None
        )
        try:
            return _CoresignalEmployee.model_validate(payload)
        except ValidationError:
            logger.error("coresignal_response_validation_failed", raw=payload)
            raise

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None) -> Any:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._retry_wait,
            retry=retry_if_exception_type((_Retryable, *_RETRYABLE_TRANSPORT)),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._attempt(method, path, json=json)
        except _Retryable as exc:
            raise exc.original from None

        raise AssertionError("unreachable: AsyncRetrying always yields or raises")

    async def _attempt(self, method: str, path: str, *, json: dict[str, Any] | None) -> Any:
        await self._rate_limiter.acquire()
        response = await self._client.request(
            method, f"{self._base_url}{path}", json=json, headers=self._headers
        )

        if response.is_success:
            return response.json()

        error = self._to_exception(response)
        if response.status_code >= 500:
            logger.warning("coresignal_request_failed_retryable", status_code=response.status_code)
            raise _Retryable(error)

        logger.warning(
            "coresignal_request_failed", status_code=response.status_code, message=error.message
        )
        raise error

    @staticmethod
    def _to_exception(response: httpx.Response) -> CoresignalAPIError:
        raw_body = response.text
        message: str | None = None
        try:
            envelope = json.loads(raw_body)
            if isinstance(envelope, dict):
                message = envelope.get("message")
        except ValueError:
            # Not JSON. Keep the raw body rather than inventing a message for it.
            pass

        exc_type = STATUS_EXCEPTIONS.get(response.status_code, CoresignalAPIError)
        return exc_type(response.status_code, message=message, raw_body=raw_body)
