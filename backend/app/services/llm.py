"""The single door every LLM call goes through (CLAUDE.md).

Responsibilities, in order:
  1. Route the call by role (compiler | simulator) to a provider+model, with a fallback.
  2. Serve from cache when possible — keyed by sha256(role, model, messages, schema name).
     Caching here is not an optimisation; it is what makes iterating on the rehearsal loop
     affordable, so it is on by default.
  3. Validate structured output into a Pydantic model, retrying ONCE with the validation error
     fed back as a user message before giving up.

Counters distinguish real provider calls from cache hits so a run can report
"42 calls, 31 cached".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, TypeVar

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from app.core.settings import Settings, get_settings
from app.integrations.llm.base import (
    LLMError,
    LLMProvider,
    LLMProviderError,
    LLMQuotaExceeded,
    LLMResponse,
    Message,
)
from app.integrations.llm.gemini import GeminiProvider
from app.integrations.llm.nvidia import NvidiaProvider
from app.models.cache import LLMCache

logger = structlog.get_logger()

Role = Literal["compiler", "simulator"]
M = TypeVar("M", bound=BaseModel)

_NO_SCHEMA = "__text__"


class LLMStructureError(LLMError):
    """The model could not produce output matching response_model, even after one retry.

    Carries the raw output so the failure is diagnosable rather than just "invalid JSON".
    """

    def __init__(
        self, model_name: str, raw_output: str, validation_error: str, *, attempts: int
    ) -> None:
        self.model_name = model_name
        self.raw_output = raw_output
        self.validation_error = validation_error
        self.attempts = attempts
        super().__init__(
            f"Could not parse LLM output into {model_name} after {attempts} attempt(s): "
            f"{validation_error}"
        )


class LLMNotConfigured(LLMError):
    """No usable provider for a role — e.g. the key for the configured provider is absent."""


@dataclass
class LLMStats:
    """Call counters. `calls` counts provider round-trips; `cached` counts cache hits.

    They are separate (not calls-minus-cached) so "42 calls, 31 cached" reads literally.
    """

    calls: int = 0
    cached: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"llm_calls": self.calls, "cached_calls": self.cached}


class LLMCacheStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def set(self, key: str, role: str, model: str, response: dict[str, Any]) -> None: ...


class InMemoryLLMCache:
    """Process-local cache. Used in tests and when no database session factory is wired in."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._entries.get(key)

    async def set(self, key: str, role: str, model: str, response: dict[str, Any]) -> None:
        self._entries[key] = response


class DatabaseLLMCache:
    """Cache backed by the llm_cache table, shared across processes and restarts.

    Opens a short session per operation via the session factory rather than holding one, so
    a cache lookup never participates in (or blocks) a caller's transaction.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def get(self, key: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(select(LLMCache).where(col(LLMCache.key) == key))
            ).scalar_one_or_none()
            return row.response if row is not None else None

    async def set(self, key: str, role: str, model: str, response: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            # ON CONFLICT DO NOTHING: two workers racing on the same key is benign — the
            # cached value is a pure function of the key, so whichever lands first is correct.
            #
            # created_at is set explicitly because this is a Core-level insert: it bypasses
            # the ORM instance construction that would normally apply the column's
            # default_factory, so without this the NOT NULL constraint fails on every write.
            await session.execute(
                pg_insert(LLMCache)
                .values(
                    key=key,
                    role=role,
                    model=model,
                    response=response,
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["key"])
            )
            await session.commit()


def cache_key(role: str, model: str, messages: list[Message], schema_name: str) -> str:
    """sha256(role, model, messages, schema name), per CLAUDE.md.

    Messages are serialised with sorted keys so an identical conversation always hashes the
    same regardless of dict ordering.
    """
    payload = json.dumps(
        {"role": role, "model": model, "messages": messages, "schema": schema_name},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class LLMService:
    """Routing, caching and validation over a set of providers."""

    def __init__(
        self,
        *,
        providers: dict[str, LLMProvider] | None = None,
        cache: LLMCacheStore | None = None,
        settings: Settings | None = None,
        cache_enabled: bool | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._providers = providers if providers is not None else _build_providers(self._settings)
        self._cache = cache if cache is not None else InMemoryLLMCache()
        self._cache_enabled = (
            self._settings.llm_cache_enabled if cache_enabled is None else cache_enabled
        )
        self.stats = LLMStats()

    # ------------------------------------------------------------------ public

    async def complete(self, role: Role, messages: list[Message], temperature: float = 0.2) -> str:
        response = await self._call(
            role, messages, temperature, schema=None, schema_name=_NO_SCHEMA
        )
        return response

    async def structured_complete(
        self,
        role: Role,
        messages: list[Message],
        response_model: type[M],
        temperature: float = 0.2,
    ) -> M:
        schema = response_model.model_json_schema()
        schema_name = response_model.__name__

        raw = await self._call(role, messages, temperature, schema=schema, schema_name=schema_name)

        try:
            return response_model.model_validate_json(raw)
        except ValidationError as first_error:
            # Bind the message here: Python unbinds the exception name at the end of the
            # except block, so it is not available further down.
            first_error_text = str(first_error)
            logger.warning("llm_structure_invalid_retrying", model=schema_name, role=role)

        # Retry ONCE, feeding the validation error back so the model can correct itself. The
        # retry deliberately bypasses the cache: the cached value is what just failed.
        repair_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "That response did not validate against the required schema.\n"
                    f"Error:\n{first_error_text}\n\n"
                    "Return ONLY corrected JSON matching the schema. No prose, no code fences."
                ),
            },
        ]
        repaired = await self._call(
            role,
            repair_messages,
            temperature,
            schema=schema,
            schema_name=schema_name,
            use_cache=False,
        )

        try:
            return response_model.model_validate_json(repaired)
        except ValidationError as second_error:
            logger.error("llm_structure_failed", model=schema_name, role=role, raw=repaired)
            raise LLMStructureError(
                schema_name, repaired, str(second_error), attempts=2
            ) from second_error

    # --------------------------------------------------------------- internals

    async def _call(
        self,
        role: Role,
        messages: list[Message],
        temperature: float,
        *,
        schema: dict[str, Any] | None,
        schema_name: str,
        use_cache: bool = True,
    ) -> str:
        primary, fallback = self._settings.llm_route(role)
        candidates = [primary] + ([fallback] if fallback else [])

        last_error: Exception | None = None
        for index, (provider_name, model) in enumerate(candidates):
            key = cache_key(role, model, messages, schema_name)

            if use_cache and self._cache_enabled:
                cached = await self._cache.get(key)
                if cached is not None:
                    self.stats.cached += 1
                    logger.debug("llm_cache_hit", role=role, model=model)
                    return str(cached.get("text", ""))

            provider = self._providers.get(provider_name)
            if provider is None:
                last_error = LLMNotConfigured(
                    f"Provider {provider_name!r} for role {role!r} is not configured "
                    "(missing API key?)"
                )
                logger.warning("llm_provider_unavailable", provider=provider_name, role=role)
                continue

            try:
                response = await self._invoke(
                    provider, model, messages, temperature, schema, schema_name
                )
            except (LLMQuotaExceeded, LLMProviderError) as exc:
                last_error = exc
                is_last = index == len(candidates) - 1
                logger.warning(
                    "llm_provider_failed",
                    provider=provider_name,
                    model=model,
                    role=role,
                    reason=type(exc).__name__,
                    falling_back=not is_last,
                )
                if is_last:
                    raise
                continue

            self.stats.calls += 1
            if use_cache and self._cache_enabled:
                await self._cache.set(key, role, model, {"text": response.text})
            return response.text

        raise last_error or LLMNotConfigured(f"No provider available for role {role!r}")

    @staticmethod
    async def _invoke(
        provider: LLMProvider,
        model: str,
        messages: list[Message],
        temperature: float,
        schema: dict[str, Any] | None,
        schema_name: str,
    ) -> LLMResponse:
        if schema is None:
            return await provider.complete(model, messages, temperature)
        return await provider.structured_complete(model, messages, schema, schema_name, temperature)

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()


def _build_providers(settings: Settings) -> dict[str, LLMProvider]:
    """Instantiate whichever providers have a key. A provider without one is simply absent,
    so the router degrades to the fallback instead of crashing at import time."""
    providers: dict[str, LLMProvider] = {}
    if settings.nvidia_api_key:
        providers["nvidia"] = NvidiaProvider(settings.nvidia_api_key)
    if settings.gemini_api_key:
        providers["gemini"] = GeminiProvider(settings.gemini_api_key)
    return providers


_default_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Process-wide default service, backed by the database cache."""
    global _default_service
    if _default_service is None:
        from app.db.session import async_session_factory

        _default_service = LLMService(cache=DatabaseLLMCache(async_session_factory))
    return _default_service


def set_llm_service(service: LLMService | None) -> None:
    """Override (or reset) the default service. Exists for tests and for wiring at startup."""
    global _default_service
    _default_service = service


async def complete(role: Role, messages: list[Message], temperature: float = 0.2) -> str:
    return await get_llm_service().complete(role, messages, temperature)


async def structured_complete[T: BaseModel](
    role: Role,
    messages: list[Message],
    response_model: type[T],
    temperature: float = 0.2,
) -> T:
    return await get_llm_service().structured_complete(role, messages, response_model, temperature)
