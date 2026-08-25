"""Shared contract for LLM providers."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

# A chat message: {"role": "system"|"user"|"assistant", "content": "..."}
Message = dict[str, str]


class LLMResponse(BaseModel):
    """What every provider returns, normalised."""

    model_config = ConfigDict(extra="allow")

    text: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMError(Exception):
    """Base for LLM adapter failures."""


class LLMProviderError(LLMError):
    """The provider failed in a way that makes it unusable for this call.

    The router treats this as grounds to try the role's secondary provider.
    """

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
        raw_body: str | None = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.raw_body = raw_body
        super().__init__(f"[{provider}] {message}")


class LLMQuotaExceeded(LLMProviderError):
    """Rate limited or out of credit (429 / 402).

    Its own type because it is an expected operational state, and because it is the single most
    likely reason to need the fallback provider mid-run.
    """


@runtime_checkable
class LLMProvider(Protocol):
    """What app/services/llm.py needs from a provider.

    Both methods return raw text. Turning that text into a validated model is the service's
    job, so that the retry-on-invalid-structure logic lives in exactly one place rather than
    being reimplemented per provider.
    """

    name: str

    async def complete(
        self, model: str, messages: list[Message], temperature: float
    ) -> LLMResponse: ...

    async def structured_complete(
        self,
        model: str,
        messages: list[Message],
        schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> LLMResponse: ...

    async def aclose(self) -> None: ...
