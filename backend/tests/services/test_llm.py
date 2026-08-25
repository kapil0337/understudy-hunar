from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.integrations.llm.base import LLMProviderError, LLMQuotaExceeded
from app.services.llm import (
    InMemoryLLMCache,
    LLMNotConfigured,
    LLMService,
    LLMStructureError,
    cache_key,
)
from tests.services.conftest import FakeProvider, SampleModel


def make_service(
    settings: Settings,
    *,
    nvidia: FakeProvider | None = None,
    gemini: FakeProvider | None = None,
    cache_enabled: bool = True,
) -> LLMService:
    providers: dict[str, FakeProvider] = {}
    if nvidia is not None:
        providers["nvidia"] = nvidia
    if gemini is not None:
        providers["gemini"] = gemini
    return LLMService(
        providers=providers,  # type: ignore[arg-type]
        cache=InMemoryLLMCache(),
        settings=settings,
        cache_enabled=cache_enabled,
    )


# ------------------------------------------------------------------------ complete()


async def test_complete_calls_primary_provider(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", ["hello there"])
    service = make_service(llm_settings, nvidia=nvidia)

    text = await service.complete("compiler", [{"role": "user", "content": "hi"}])

    assert text == "hello there"
    assert nvidia.calls[0]["kind"] == "complete"
    assert nvidia.calls[0]["model"] == "model-a"
    assert service.stats.calls == 1
    assert service.stats.cached == 0


async def test_complete_uses_role_specific_routing(llm_settings: Settings) -> None:
    llm_settings.llm_model_simulator = "different-model"
    nvidia = FakeProvider("nvidia", ["a", "b"])
    service = make_service(llm_settings, nvidia=nvidia)

    await service.complete("compiler", [{"role": "user", "content": "x"}])
    await service.complete("simulator", [{"role": "user", "content": "x"}])

    assert nvidia.calls[0]["model"] == "model-a"
    assert nvidia.calls[1]["model"] == "different-model"


# -------------------------------------------------------------------------- caching


async def test_second_identical_call_is_served_from_cache(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", ["only one response scripted"])
    service = make_service(llm_settings, nvidia=nvidia)
    messages = [{"role": "user", "content": "hi"}]

    first = await service.complete("compiler", messages)
    second = await service.complete("compiler", messages)

    assert first == second == "only one response scripted"
    assert service.stats.calls == 1
    assert service.stats.cached == 1  # counted separately, not calls-minus-hits


async def test_cache_disabled_calls_provider_every_time(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", ["r1", "r2"])
    service = make_service(llm_settings, nvidia=nvidia, cache_enabled=False)
    messages = [{"role": "user", "content": "hi"}]

    first = await service.complete("compiler", messages)
    second = await service.complete("compiler", messages)

    assert (first, second) == ("r1", "r2")
    assert service.stats.calls == 2
    assert service.stats.cached == 0


async def test_different_messages_do_not_share_a_cache_entry(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", ["r1", "r2"])
    service = make_service(llm_settings, nvidia=nvidia)

    await service.complete("compiler", [{"role": "user", "content": "one"}])
    await service.complete("compiler", [{"role": "user", "content": "two"}])

    assert service.stats.calls == 2
    assert service.stats.cached == 0


async def test_different_roles_do_not_share_a_cache_entry_even_with_same_model(
    llm_settings: Settings,
) -> None:
    llm_settings.llm_model_simulator = llm_settings.llm_model_compiler
    nvidia = FakeProvider("nvidia", ["r1", "r2"])
    service = make_service(llm_settings, nvidia=nvidia)
    messages = [{"role": "user", "content": "same text"}]

    await service.complete("compiler", messages)
    await service.complete("simulator", messages)

    assert service.stats.calls == 2


def test_cache_key_is_stable_regardless_of_message_dict_order() -> None:
    a = cache_key("compiler", "m", [{"role": "user", "content": "hi"}], "schema")
    b = cache_key("compiler", "m", [{"content": "hi", "role": "user"}], "schema")

    assert a == b


def test_cache_key_differs_by_schema_name() -> None:
    messages = [{"role": "user", "content": "hi"}]

    a = cache_key("compiler", "m", messages, "SchemaA")
    b = cache_key("compiler", "m", messages, "SchemaB")

    assert a != b


# -------------------------------------------------------------------------- fallback


async def test_falls_back_to_secondary_on_quota_exceeded(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", [LLMQuotaExceeded("nvidia", "out of credit")])
    gemini = FakeProvider("gemini", ["from gemini"])
    service = make_service(llm_settings, nvidia=nvidia, gemini=gemini)

    text = await service.complete("compiler", [{"role": "user", "content": "hi"}])

    assert text == "from gemini"
    assert len(nvidia.calls) == 1
    assert len(gemini.calls) == 1
    assert service.stats.calls == 1  # only the successful call counts


async def test_falls_back_to_secondary_on_provider_error(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", [LLMProviderError("nvidia", "HTTP 500")])
    gemini = FakeProvider("gemini", ["from gemini"])
    service = make_service(llm_settings, nvidia=nvidia, gemini=gemini)

    text = await service.complete("compiler", [{"role": "user", "content": "hi"}])

    assert text == "from gemini"


async def test_fallback_is_logged(llm_settings: Settings) -> None:
    import structlog

    nvidia = FakeProvider("nvidia", [LLMQuotaExceeded("nvidia", "out of credit")])
    gemini = FakeProvider("gemini", ["from gemini"])
    service = make_service(llm_settings, nvidia=nvidia, gemini=gemini)

    # capture_logs() works regardless of the module-level logger already being resolved and
    # cached by an earlier test — reconfiguring structlog.configure() directly does not,
    # since structlog's lazy proxy resolves and caches itself on first use.
    with structlog.testing.capture_logs() as events:
        await service.complete("compiler", [{"role": "user", "content": "hi"}])

    fallback_events = [e for e in events if e.get("event") == "llm_provider_failed"]
    assert len(fallback_events) == 1
    assert fallback_events[0]["provider"] == "nvidia"
    assert fallback_events[0]["falling_back"] is True


async def test_raises_when_both_providers_fail(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", [LLMQuotaExceeded("nvidia", "out")])
    gemini = FakeProvider("gemini", [LLMProviderError("gemini", "HTTP 503")])
    service = make_service(llm_settings, nvidia=nvidia, gemini=gemini)

    with pytest.raises(LLMProviderError):
        await service.complete("compiler", [{"role": "user", "content": "hi"}])


async def test_missing_primary_provider_falls_back(llm_settings: Settings) -> None:
    """The primary's key is simply absent (not in the providers dict) — same as any other
    provider failure from the router's point of view."""
    gemini = FakeProvider("gemini", ["from gemini"])
    service = make_service(llm_settings, gemini=gemini)  # no nvidia

    text = await service.complete("compiler", [{"role": "user", "content": "hi"}])

    assert text == "from gemini"


async def test_no_provider_configured_raises_not_configured(llm_settings: Settings) -> None:
    service = make_service(llm_settings)  # neither provider

    with pytest.raises(LLMNotConfigured):
        await service.complete("compiler", [{"role": "user", "content": "hi"}])


async def test_no_fallback_configured_raises_primary_error(llm_settings: Settings) -> None:
    llm_settings.llm_fallback_provider_compiler = None
    llm_settings.llm_fallback_model_compiler = None
    nvidia = FakeProvider("nvidia", [LLMProviderError("nvidia", "HTTP 500")])
    service = make_service(llm_settings, nvidia=nvidia)

    with pytest.raises(LLMProviderError):
        await service.complete("compiler", [{"role": "user", "content": "hi"}])


# --------------------------------------------------------------- structured_complete


async def test_structured_complete_parses_valid_json(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", [json.dumps({"name": "a", "count": 1})])
    service = make_service(llm_settings, nvidia=nvidia)

    result = await service.structured_complete(
        "compiler", [{"role": "user", "content": "x"}], SampleModel
    )

    assert result == SampleModel(name="a", count=1)
    assert len(nvidia.calls) == 1


async def test_structured_complete_retries_once_on_invalid_json(llm_settings: Settings) -> None:
    nvidia = FakeProvider(
        "nvidia",
        [
            json.dumps({"name": "a"}),  # missing 'count' -> invalid
            json.dumps({"name": "a", "count": 2}),  # corrected
        ],
    )
    service = make_service(llm_settings, nvidia=nvidia)

    result = await service.structured_complete(
        "compiler", [{"role": "user", "content": "x"}], SampleModel
    )

    assert result == SampleModel(name="a", count=2)
    assert len(nvidia.calls) == 2
    # The repair call must include the validation error so the model can self-correct.
    repair_call = nvidia.calls[1]
    assert repair_call["messages"][-2]["role"] == "assistant"
    assert repair_call["messages"][-1]["role"] == "user"
    assert "count" in repair_call["messages"][-1]["content"]


async def test_structured_complete_raises_llm_structure_error_after_second_failure(
    llm_settings: Settings,
) -> None:
    nvidia = FakeProvider(
        "nvidia",
        [
            json.dumps({"name": "a"}),
            "not json at all",
        ],
    )
    service = make_service(llm_settings, nvidia=nvidia)

    with pytest.raises(LLMStructureError) as excinfo:
        await service.structured_complete(
            "compiler", [{"role": "user", "content": "x"}], SampleModel
        )

    assert excinfo.value.raw_output == "not json at all"
    assert excinfo.value.attempts == 2
    assert excinfo.value.model_name == "SampleModel"


async def test_structured_complete_retry_bypasses_cache(llm_settings: Settings) -> None:
    """The repair call must not be served from (or write to) the cache — the cached value is
    exactly what just failed to validate."""
    nvidia = FakeProvider(
        "nvidia",
        [json.dumps({"name": "a"}), json.dumps({"name": "a", "count": 3})],
    )
    service = make_service(llm_settings, nvidia=nvidia)

    await service.structured_complete("compiler", [{"role": "user", "content": "x"}], SampleModel)

    assert service.stats.cached == 0  # nothing was a cache hit
    assert service.stats.calls == 2  # both provider calls counted


async def test_structured_complete_sends_json_schema(llm_settings: Settings) -> None:
    nvidia = FakeProvider("nvidia", [json.dumps({"name": "a", "count": 1})])
    service = make_service(llm_settings, nvidia=nvidia)

    await service.structured_complete("compiler", [{"role": "user", "content": "x"}], SampleModel)

    call = nvidia.calls[0]
    assert call["kind"] == "structured"
    assert call["schema_name"] == "SampleModel"
    assert "count" in call["schema"]["properties"]


async def test_structured_complete_falls_back_before_retrying(llm_settings: Settings) -> None:
    """A provider failure (not an invalid structure) should trigger the normal fallback path,
    not the validate-and-repair path."""
    nvidia = FakeProvider("nvidia", [LLMQuotaExceeded("nvidia", "out")])
    gemini = FakeProvider("gemini", [json.dumps({"name": "a", "count": 1})])
    service = make_service(llm_settings, nvidia=nvidia, gemini=gemini)

    result = await service.structured_complete(
        "compiler", [{"role": "user", "content": "x"}], SampleModel
    )

    assert result == SampleModel(name="a", count=1)
    assert len(nvidia.calls) == 1
    assert len(gemini.calls) == 1


# -------------------------------------------------------------------- database cache


async def test_database_cache_round_trips_through_real_table(
    db_session: AsyncSession,
) -> None:
    """Smoke check that DatabaseLLMCache reads/writes the real llm_cache table correctly."""
    from contextlib import asynccontextmanager

    from app.services.llm import DatabaseLLMCache

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    cache = DatabaseLLMCache(factory)
    key = "test-key-1"

    assert await cache.get(key) is None

    await cache.set(key, "compiler", "model-a", {"text": "hello"})
    result = await cache.get(key)

    assert result == {"text": "hello"}


async def test_database_cache_set_is_idempotent_on_conflict(db_session: AsyncSession) -> None:
    """ON CONFLICT DO NOTHING: writing the same key twice must not raise."""
    from contextlib import asynccontextmanager

    from app.services.llm import DatabaseLLMCache

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    cache = DatabaseLLMCache(factory)
    key = "test-key-2"

    await cache.set(key, "compiler", "model-a", {"text": "first"})
    await cache.set(key, "compiler", "model-a", {"text": "second"})  # must not raise

    # First write wins — the cached value is a pure function of the key.
    assert await cache.get(key) == {"text": "first"}
