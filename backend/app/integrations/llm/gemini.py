"""Google Gemini provider — native schema-constrained output.

Gemini does not take an OpenAI-style response_format. It constrains generation with
generationConfig.responseMimeType + responseSchema, which is a restricted subset of OpenAPI
schema: it rejects the JSON Schema keywords a Pydantic model emits by default, so schemas are
translated in _to_gemini_schema before being sent.
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

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_ATTEMPTS = 3

_RETRYABLE_TRANSPORT = (httpx.TimeoutException, httpx.TransportError)

# responseSchema accepts only these; anything else is rejected or silently ignored.
_ALLOWED_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "items",
    "properties",
    "required",
    "minItems",
    "maxItems",
}


class _Retryable(Exception):
    def __init__(self, original: LLMProviderError) -> None:
        self.original = original
        super().__init__(str(original))


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate a JSON Schema (as Pydantic emits) into Gemini's responseSchema subset.

    Inlines $ref/$defs, since Gemini has no notion of either, and drops unsupported keywords
    rather than sending them and having the request rejected.
    """
    defs = schema.get("$defs", {})

    def convert(node: Any) -> Any:
        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            ref = node["$ref"]
            name = ref.rsplit("/", 1)[-1]
            target = defs.get(name)
            if target is None:
                logger.warning("gemini_schema_unresolved_ref", ref=ref)
                return {"type": "string"}
            return convert(target)

        # anyOf is how Pydantic renders `X | None`; take the non-null branch and mark nullable.
        if "anyOf" in node:
            branches = [b for b in node["anyOf"] if b.get("type") != "null"]
            nullable = len(branches) != len(node["anyOf"])
            converted = convert(branches[0]) if branches else {"type": "string"}
            if nullable and isinstance(converted, dict):
                converted["nullable"] = True
            return converted

        out: dict[str, Any] = {}
        for key, value in node.items():
            if key not in _ALLOWED_SCHEMA_KEYS:
                continue
            if key == "properties" and isinstance(value, dict):
                out[key] = {k: convert(v) for k, v in value.items()}
            elif key == "items":
                out[key] = convert(value)
            else:
                out[key] = value
        return out

    converted = convert({k: v for k, v in schema.items() if k != "$defs"})
    return converted if isinstance(converted, dict) else {"type": "object"}


def _to_gemini_contents(messages: list[Message]) -> tuple[list[dict[str, Any]], str | None]:
    """Split chat messages into Gemini's (contents, systemInstruction).

    Gemini takes system prompts separately and uses "model" where OpenAI uses "assistant".
    """
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role", "user")
        text = message.get("content", "")
        if role == "system":
            system_parts.append(text)
            continue
        contents.append(
            {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
        )

    system = "\n\n".join(system_parts) if system_parts else None
    return contents, system


class GeminiProvider:
    name = "gemini"

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
            raise ValueError("Gemini api_key must not be empty")

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts
        self._retry_wait: WaitBaseT = retry_wait or wait_exponential(multiplier=0.5, min=0.5, max=8)
        # Key travels in a header, not the query string, so it cannot leak via request logs.
        self._headers = {
            "x-goog-api-key": api_key,
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
        contents, system = _to_gemini_contents(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return await self._generate(model, payload)

    async def structured_complete(
        self,
        model: str,
        messages: list[Message],
        schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> LLMResponse:
        contents, system = _to_gemini_contents(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": _to_gemini_schema(schema),
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return await self._generate(model, payload)

    async def _generate(self, model: str, payload: dict[str, Any]) -> LLMResponse:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._retry_wait,
            retry=retry_if_exception_type((_Retryable, *_RETRYABLE_TRANSPORT)),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._attempt(model, payload)
        except _Retryable as exc:
            raise exc.original from None
        except _RETRYABLE_TRANSPORT as exc:
            # Retries exhausted on a timeout/connection failure. Wrap so the router
            # (app/services/llm.py) sees LLMProviderError and falls back, per the documented
            # contract in app/integrations/llm/base.py — a bare httpx exception here would
            # otherwise escape uncaught and skip the fallback provider entirely.
            raise LLMProviderError(self.name, f"{type(exc).__name__}: {exc}") from exc

        raise AssertionError("unreachable: AsyncRetrying always yields or raises")

    async def _attempt(self, model: str, payload: dict[str, Any]) -> LLMResponse:
        response = await self._client.post(
            f"{self._base_url}/models/{model}:generateContent",
            json=payload,
            headers=self._headers,
        )

        if response.is_success:
            return self._parse(response.json(), model)

        body = response.text
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
            logger.warning("gemini_retryable_error", status_code=response.status_code)
            raise _Retryable(error)
        raise error

    def _parse(self, data: Any, model: str) -> LLMResponse:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("gemini_unexpected_response_shape", raw=data)
            raise LLMProviderError(
                self.name, "unexpected response shape", raw_body=str(data)
            ) from exc

        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            model=model,
            provider=self.name,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
        )
