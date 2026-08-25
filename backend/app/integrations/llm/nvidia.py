"""NVIDIA NIM provider — OpenAI-compatible chat completions.

Structured output uses response_format={"type": "json_schema", ...}, the OpenAI-compatible
mechanism NVIDIA exposes.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

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

logger = structlog.get_logger()

BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TIMEOUT = 120.0  # generation is slow; well above the 30s used for control-plane APIs
DEFAULT_MAX_ATTEMPTS = 3

_RETRYABLE_TRANSPORT = (httpx.TimeoutException, httpx.TransportError)


class _Retryable(Exception):
    """Internal marker for a 5xx worth retrying; never escapes a public method."""

    def __init__(self, original: LLMProviderError) -> None:
        self.original = original
        super().__init__(str(original))


class NvidiaProvider:
    name = "nvidia"

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
            raise ValueError("NVIDIA api_key must not be empty")

        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts
        self._retry_wait: WaitBaseT = retry_wait or wait_exponential(multiplier=0.5, min=0.5, max=8)
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
        response = await self._client.post(
            f"{self._base_url}/chat/completions", json=payload, headers=self._headers
        )

        if response.is_success:
            return self._parse(response.json(), payload["model"])

        body = response.text
        # 429 rate limit / 402 out of credit — both mean "use the other provider", not "retry".
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
            logger.warning("nvidia_retryable_error", status_code=response.status_code)
            raise _Retryable(error)
        raise error

    def _parse(self, data: Any, model: str) -> LLMResponse:
        try:
            choice = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            # Never invent a shape we did not get — log the raw payload and fail.
            logger.error("nvidia_unexpected_response_shape", raw=data)
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
