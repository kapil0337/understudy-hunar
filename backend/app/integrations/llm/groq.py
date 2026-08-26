"""Groq provider — OpenAI-compatible chat completions.

Structured output uses response_format={"type": "json_schema", ...}, the same OpenAI-compatible
mechanism app/integrations/llm/nvidia.py uses — Groq's API is a near-exact match, so this mirrors
that adapter closely rather than inventing a different shape for the same contract.

Rate limiting, unlike nvidia.py/gemini.py, is real here: this account's Groq plan is limited to
8000 tokens/minute (verified live via the x-ratelimit-limit-tokens response header), and
rehearsal's concurrent per-persona calls blow through that in seconds without it — a burst of
~10 simultaneous calls hit 429s outright before this was added. TokenBucket rate-limits by
request count, not tokens (the actual cost of a call isn't known ahead of it), so
DEFAULT_RATE_LIMIT_REQUESTS is a conservative approximation, not an exact token budget.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any, NoReturn, Self

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import WaitBaseT

from app.integrations.llm.base import (
    LLMProviderError,
    LLMQuotaExceeded,
    LLMResponse,
    Message,
)
from app.integrations.ratelimit import TokenBucket

logger = structlog.get_logger()

BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_TIMEOUT = 120.0  # generation is slow; well above the 30s used for control-plane APIs
DEFAULT_MAX_ATTEMPTS = 3
#: 8000 tokens/minute account budget (verified live via x-ratelimit-limit-tokens). Sized off
#: real measurements — a bare "hi" costs ~77 tokens, a short simulator turn ~225 — leaving
#: headroom for a rehearsal transcript's prompt growing across turns without assuming every
#: call is minimal-cost. Push this higher only with fresh live evidence, not a guess: too high
#: means every persona's simulation fails outright on a 429, not just runs slower.
DEFAULT_RATE_LIMIT_REQUESTS = 15
DEFAULT_RATE_LIMIT_PERIOD_SECONDS = 60.0
#: A 429 specifically gets its own, longer-waiting retry (see _attempt) rather than the fast
#: tenacity retry below meant for 5xx/transport errors: the coverage/faithfulness judge calls
#: batch every persona's transcript into one big call, so it can cost more tokens than
#: DEFAULT_RATE_LIMIT_REQUESTS's flat per-request budget assumed, hitting a 429 right after a
#: rehearsal's other 6-10 calls already succeeded. nvidia.py/gemini.py treat 429 as "stop, let
#: the router fall back to the next provider" — correct when there is one; wrong here, since
#: Groq is currently the only provider actually working, so giving up immediately means
#: discarding a run's already-completed persona simulations over one transient rate limit.
MAX_RATE_LIMIT_RETRIES = 2
DEFAULT_RATE_LIMIT_RETRY_WAIT_SECONDS = 12.0

_RETRYABLE_TRANSPORT = (httpx.TimeoutException, httpx.TransportError)


class _Retryable(Exception):
    """Internal marker for a 5xx worth retrying; never escapes a public method."""

    def __init__(self, original: LLMProviderError) -> None:
        self.original = original
        super().__init__(str(original))


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_wait: WaitBaseT | None = None,
        rate_limiter: TokenBucket | None = None,
        rate_limit_retry_wait_seconds: float = DEFAULT_RATE_LIMIT_RETRY_WAIT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Groq api_key must not be empty")

        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts
        self._retry_wait: WaitBaseT = retry_wait or wait_exponential(multiplier=0.5, min=0.5, max=8)
        self._rate_limiter = rate_limiter or TokenBucket(
            DEFAULT_RATE_LIMIT_REQUESTS, DEFAULT_RATE_LIMIT_PERIOD_SECONDS
        )
        # Separate from retry_wait above: that paces tenacity's 5xx/transport retry, this paces
        # the 429-specific loop in _attempt, which needs to wait long enough for the account's
        # per-minute token budget to actually recover, not tenacity's sub-second backoff curve.
        self._rate_limit_retry_wait_seconds = rate_limit_retry_wait_seconds
        # Headers per-request so an injected client behaves identically to one we build.
        self._headers = {
            "Authorization": f"Bearer {api_key}",
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

    async def complete(
        self, model: str, messages: list[Message], temperature: float
    ) -> LLMResponse:
        return await self._chat({"model": model, "messages": messages, "temperature": temperature})

    async def structured_complete(
        self,
        model: str,
        messages: list[Message],
        schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> LLMResponse:
        return await self._chat(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
            }
        )

    async def _chat(self, payload: dict[str, Any]) -> LLMResponse:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._retry_wait,
            retry=retry_if_exception_type((_Retryable, *_RETRYABLE_TRANSPORT)),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._attempt(payload)
        except _Retryable as exc:
            raise exc.original from None
        except _RETRYABLE_TRANSPORT as exc:
            # Retries exhausted on a timeout/connection failure. Wrap so the router
            # (app/services/llm.py) sees LLMProviderError and falls back, per the documented
            # contract in app/integrations/llm/base.py — a bare httpx exception here would
            # otherwise escape uncaught and skip the fallback provider entirely.
            raise LLMProviderError(self.name, f"{type(exc).__name__}: {exc}") from exc

        raise AssertionError("unreachable: AsyncRetrying always yields or raises")

    async def _attempt(self, payload: dict[str, Any]) -> LLMResponse:
        for rate_limit_attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            await self._rate_limiter.acquire()
            response = await self._client.post(
                f"{self._base_url}/chat/completions", json=payload, headers=self._headers
            )

            if response.is_success:
                return self._parse(response.json(), payload["model"])

            if response.status_code == 429 and rate_limit_attempt < MAX_RATE_LIMIT_RETRIES:
                wait_seconds = self._retry_after_seconds(response)
                logger.warning(
                    "groq_rate_limited_retrying",
                    attempt=rate_limit_attempt + 1,
                    wait_seconds=wait_seconds,
                )
                await asyncio.sleep(wait_seconds)
                continue

            return self._raise_for_status(response)

        raise AssertionError("unreachable: the loop above always returns or raises")

    def _retry_after_seconds(self, response: httpx.Response) -> float:
        # Groq does not document sending Retry-After on a 429; check anyway rather than assume
        # it is absent, and fall back to self._rate_limit_retry_wait_seconds if it is missing or
        # unparseable.
        header = response.headers.get("retry-after")
        if header is None:
            return self._rate_limit_retry_wait_seconds
        try:
            return max(0.0, float(header))
        except ValueError:
            return self._rate_limit_retry_wait_seconds

    def _raise_for_status(self, response: httpx.Response) -> NoReturn:
        body = response.text
        # 402 out of credit, or a 429 with MAX_RATE_LIMIT_RETRIES already spent above: both mean
        # give up rather than retry further.
        if response.status_code in (402, 429):
            raise LLMQuotaExceeded(
                self.name,
                "quota exceeded or rate limited",
                status_code=response.status_code,
                raw_body=body,
            )

        error = LLMProviderError(
            self.name,
            f"HTTP {response.status_code}",
            status_code=response.status_code,
            raw_body=body,
        )
        if response.status_code >= 500:
            logger.warning("groq_retryable_error", status_code=response.status_code)
            raise _Retryable(error)
        raise error

    def _parse(self, data: Any, model: str) -> LLMResponse:
        try:
            choice = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            # Never invent a shape we did not get — log the raw payload and fail.
            logger.error("groq_unexpected_response_shape", raw=data)
            raise LLMProviderError(
                self.name, "unexpected response shape", raw_body=str(data)
            ) from exc

        usage = data.get("usage") or {}
        return LLMResponse(
            text=choice or "",
            model=data.get("model") or model,
            provider=self.name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
