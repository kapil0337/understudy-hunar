"""Async client for the Hunar Voice Agents API.

Retry policy: 5xx and connect/timeout errors only, never 4xx. A 422 or a 402 will not become
truthy by asking again — retrying them just burns time and, for call creation, risks duplicate
side effects. Only genuinely transient failures are retried.
"""

from __future__ import annotations

import json
from types import TracebackType
from typing import Any, Self, TypeVar
from urllib.parse import urljoin

import httpx
import structlog
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import WaitBaseT

from app.integrations.hunar.exceptions import STATUS_EXCEPTIONS, HunarAPIError
from app.integrations.hunar.models import (
    Agent,
    AgentCreate,
    AgentUpdate,
    Call,
    CallCreate,
    HunarError,
    Paginated,
    PhoneNumber,
)

logger = structlog.get_logger()

BASE_URL = "https://api.voice.hunar.ai/external/v1/"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_ATTEMPTS = 3

M = TypeVar("M", bound=BaseModel)


class HunarRetryableError(Exception):
    """Internal marker for a failure worth retrying (5xx). Never escapes a public method:
    the final attempt re-raises the underlying HunarAPIError instead."""

    def __init__(self, original: HunarAPIError) -> None:
        self.original = original
        super().__init__(str(original))


#: Transport-level failures worth retrying. httpx.TimeoutException covers connect/read/write
#: timeouts; httpx.ConnectError and friends cover a refused or broken connection.
_RETRYABLE_TRANSPORT = (httpx.TimeoutException, httpx.TransportError)


class HunarClient:
    """Thin, typed wrapper over the Hunar REST API.

    Usage:
        async with HunarClient(api_key) as client:
            agents = await client.list_agents()
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_wait: WaitBaseT | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")

        self._api_key = api_key
        self._base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self._max_attempts = max_attempts
        # Injectable so tests can drop the backoff; production always gets real backoff.
        self._retry_wait: WaitBaseT = (
            retry_wait
            if retry_wait is not None
            else wait_exponential(multiplier=0.5, min=0.5, max=8)
        )
        # Auth and content headers are attached per-request, and URLs are resolved against
        # _base_url here rather than relying on the client's own base_url. That way an
        # injected httpx.AsyncClient behaves identically to one we build — otherwise a caller
        # supplying their own client would silently send unauthenticated, relative requests.
        self._headers = {
            "X-API-Key": api_key,
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

    # ------------------------------------------------------------------ agents

    async def list_agents(self) -> Paginated[Agent]:
        payload = await self._request("GET", "agents/")
        return self._parse(Paginated[Agent], payload)

    async def get_agent(self, agent_id: str) -> Agent:
        payload = await self._request("GET", f"agents/{agent_id}/")
        return self._parse(Agent, payload)

    async def create_agent(self, agent: AgentCreate) -> Agent:
        payload = await self._request("POST", "agents/", json=self._dump(agent))
        return self._parse(Agent, payload)

    async def update_agent(self, agent_id: str, agent: AgentUpdate) -> Agent:
        payload = await self._request("PUT", f"agents/{agent_id}/", json=self._dump(agent))
        return self._parse(Agent, payload)

    # ------------------------------------------------------------------- calls

    async def create_call(self, call: CallCreate) -> Call:
        payload = await self._request("POST", "calls/", json=self._dump(call))
        return self._parse(Call, payload)

    async def list_calls(self, **params: Any) -> Paginated[Call]:
        payload = await self._request("GET", "calls/", params=params or None)
        return self._parse(Paginated[Call], payload)

    async def get_call(self, call_id: str) -> Call:
        payload = await self._request("GET", f"calls/{call_id}/")
        return self._parse(Call, payload)

    # ----------------------------------------------------------------- numbers

    async def list_numbers(self) -> Paginated[PhoneNumber]:
        payload = await self._request("GET", "numbers/")
        return self._parse(Paginated[PhoneNumber], payload)

    # ---------------------------------------------------------------- internals

    @staticmethod
    def _dump(model: BaseModel) -> dict[str, Any]:
        # exclude_none so an omitted retry_config/guardrails stays omitted (inheriting org
        # defaults) rather than being sent as an explicit null, which reads as "incomplete".
        return model.model_dump(mode="json", exclude_none=True)

    @staticmethod
    def _parse(model: type[M], payload: Any) -> M:
        try:
            return model.model_validate(payload)
        except ValidationError:
            # Never guess at a shape we did not expect — log the raw response and fail loudly.
            logger.error("hunar_response_validation_failed", model=model.__name__, raw=payload)
            raise

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue a request, retrying only transient failures, and translate error statuses."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._retry_wait,
            retry=retry_if_exception_type((HunarRetryableError, *_RETRYABLE_TRANSPORT)),
            reraise=True,
        )

        try:
            async for attempt in retrying:
                with attempt:
                    return await self._attempt(method, path, json=json, params=params)
        except HunarRetryableError as exc:
            # Retries exhausted on a 5xx: surface the real API error, not the marker.
            raise exc.original from None

        raise AssertionError("unreachable: AsyncRetrying always yields or raises")

    async def _attempt(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> Any:
        url = urljoin(self._base_url, path.lstrip("/"))
        response = await self._client.request(
            method, url, json=json, params=params, headers=self._headers
        )

        if response.is_success:
            if not response.content:
                return None
            return response.json()

        error = self._to_exception(response)
        if response.status_code >= 500:
            logger.warning(
                "hunar_request_failed_retryable",
                method=method,
                path=path,
                status_code=response.status_code,
            )
            raise HunarRetryableError(error)

        logger.warning(
            "hunar_request_failed",
            method=method,
            path=path,
            status_code=response.status_code,
            message=error.message,
        )
        raise error

    @staticmethod
    def _to_exception(response: httpx.Response) -> HunarAPIError:
        raw_body = response.text
        message: str | None = None
        details: Any = None

        try:
            envelope = HunarError.model_validate(json.loads(raw_body))
            message = envelope.message
            details = envelope.details
        except (ValueError, ValidationError):
            # Not the documented {success, message, details} envelope. Keep the raw body
            # rather than inventing a message for it.
            pass

        exc_type = STATUS_EXCEPTIONS.get(response.status_code, HunarAPIError)
        return exc_type(response.status_code, message=message, details=details, raw_body=raw_body)
