"""People Data Labs Person Search provider.

Free tier facts that shape everything below (see CLAUDE.md):
  - 100 credits/month, so `query.limit` is hard-capped at MAX_RESULTS_PER_SEARCH regardless of
    what the caller asked for.
  - 10 requests/minute, enforced here with a token bucket rather than trusted to the caller.
  - Contact fields (phone_numbers, personal_emails, ...) come back as a bare `true`/`false` flag
    on this tier instead of actual values — PDL's documented sandbox behaviour for fields your
    plan doesn't include. So phone_numbers is parsed defensively as `bool | list[str] | None`,
    and EITHER shape is reduced to `has_phone_flag` only. The literal value, even on a higher
    tier that returned real numbers, is deliberately never carried into SourcedCandidate:
    phone_e164 is only ever set by the consent flow (app/services/consent.py), never by a
    sourcing provider.

We do not have a live key to validate the exact response shape against, so parsing uses
extra="allow" throughout and logs the raw payload on anything unexpected rather than guessing
at undocumented fields.
"""

from __future__ import annotations

import json
from types import TracebackType
from typing import Any, Self

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import WaitBaseT

from app.integrations.sourcing.base import (
    SourcedCandidate,
    SourcingQuery,
    SourcingResult,
)
from app.integrations.sourcing.exceptions import STATUS_EXCEPTIONS, PDLAPIError
from app.integrations.ratelimit import TokenBucket

logger = structlog.get_logger()

BASE_URL = "https://api.peopledatalabs.com/v5/person/search"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_ATTEMPTS = 3

#: Free tier is 100 credits/month — never let one search burn more than this, no matter what
#: the caller passed as SourcingQuery.limit.
MAX_RESULTS_PER_SEARCH = 10
#: Free tier's documented rate limit.
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_PERIOD_SECONDS = 60.0

_RETRYABLE_TRANSPORT = (httpx.TimeoutException, httpx.TransportError)


class _Retryable(Exception):
    """Internal marker for a 5xx worth retrying; never escapes a public method."""

    def __init__(self, original: PDLAPIError) -> None:
        self.original = original
        super().__init__(str(original))


class _PDLPerson(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    job_company_name: str | None = None
    location_name: str | None = None
    skills: list[str] | None = None
    inferred_years_experience: float | None = None
    linkedin_url: str | None = None
    # Free tier: a bare bool flag, not a value. See module docstring.
    phone_numbers: bool | list[str] | None = None


class _PDLSearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: int | None = None
    data: list[_PDLPerson] = Field(default_factory=list)


def _has_phone(phone_numbers: bool | list[str] | None) -> bool:
    if isinstance(phone_numbers, bool):
        return phone_numbers
    if isinstance(phone_numbers, list):
        return len(phone_numbers) > 0
    return False


def _to_sourced_candidate(person: _PDLPerson) -> SourcedCandidate:
    return SourcedCandidate(
        source_ref=person.id or person.linkedin_url or person.full_name or "unknown",
        full_name=person.full_name or "Unknown",
        headline=(
            f"{person.job_title} at {person.job_company_name}"
            if person.job_title and person.job_company_name
            else person.job_title
        ),
        current_title=person.job_title,
        current_company=person.job_company_name,
        location=person.location_name,
        skills=person.skills or [],
        years_experience=person.inferred_years_experience,
        linkedin_url=person.linkedin_url,
        preferred_language=None,  # PDL does not report spoken language; never guessed at.
        has_phone_flag=_has_phone(person.phone_numbers),
        needs_phone=True,
        raw=person.model_dump(mode="json"),
    )


def build_search_body(query: SourcingQuery) -> dict[str, Any]:
    """Elasticsearch-style bool query over PDL's person index."""
    must: list[dict[str, Any]] = []
    if query.titles:
        must.append({"terms": {"job_title": [t.lower() for t in query.titles]}})
    if query.skills:
        must.append({"terms": {"skills": [s.lower() for s in query.skills]}})
    if query.locations:
        must.append({"terms": {"location_locality": [loc.lower() for loc in query.locations]}})
    if query.min_years is not None:
        must.append({"range": {"inferred_years_experience": {"gte": query.min_years}}})

    es_query: dict[str, Any] = {"bool": {"must": must}} if must else {"match_all": {}}
    size = min(query.limit, MAX_RESULTS_PER_SEARCH)
    return {"query": es_query, "size": size}


class PDLProvider:
    name = "pdl"

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
            raise ValueError("PDL api_key must not be empty")

        self._base_url = base_url
        self._max_attempts = max_attempts
        self._retry_wait: WaitBaseT = retry_wait or wait_exponential(multiplier=0.5, min=0.5, max=8)
        self._rate_limiter = rate_limiter or TokenBucket(
            RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD_SECONDS
        )
        self._headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
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
        body = build_search_body(query)
        payload = await self._request(body)
        candidates = [_to_sourced_candidate(person) for person in payload.data]
        return SourcingResult(provider=self.name, candidates=candidates, cached=False)

    # ---------------------------------------------------------------- internals

    async def _request(self, body: dict[str, Any]) -> _PDLSearchResponse:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._retry_wait,
            retry=retry_if_exception_type((_Retryable, *_RETRYABLE_TRANSPORT)),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._attempt(body)
        except _Retryable as exc:
            raise exc.original from None

        raise AssertionError("unreachable: AsyncRetrying always yields or raises")

    async def _attempt(self, body: dict[str, Any]) -> _PDLSearchResponse:
        await self._rate_limiter.acquire()
        response = await self._client.post(self._base_url, json=body, headers=self._headers)

        if response.is_success:
            return self._parse(response.json())

        error = self._to_exception(response)
        if response.status_code >= 500:
            logger.warning("pdl_request_failed_retryable", status_code=response.status_code)
            raise _Retryable(error)

        logger.warning(
            "pdl_request_failed", status_code=response.status_code, message=error.message
        )
        raise error

    @staticmethod
    def _parse(payload: Any) -> _PDLSearchResponse:
        try:
            return _PDLSearchResponse.model_validate(payload)
        except ValidationError:
            logger.error("pdl_response_validation_failed", raw=payload)
            raise

    @staticmethod
    def _to_exception(response: httpx.Response) -> PDLAPIError:
        raw_body = response.text
        message: str | None = None
        details: Any = None
        try:
            envelope = json.loads(raw_body)
            error = envelope.get("error") if isinstance(envelope, dict) else None
            if isinstance(error, dict):
                message = error.get("message")
                details = error
            elif isinstance(envelope, dict):
                message = envelope.get("message")
        except ValueError:
            # Not JSON. Keep the raw body rather than inventing a message for it.
            pass

        exc_type = STATUS_EXCEPTIONS.get(response.status_code, PDLAPIError)
        return exc_type(response.status_code, message=message, details=details, raw_body=raw_body)
