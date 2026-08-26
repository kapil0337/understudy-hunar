from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.integrations.sourcing.base import (
    SourcedCandidate,
    SourcingAuthError,
    SourcingQuery,
    SourcingQuotaExceeded,
    SourcingResult,
)
from app.services.sourcing import SourcingService, sourcing_cache_key

_CANDIDATE = SourcedCandidate(source_ref="c1", full_name="Test Candidate")


class FakeSourcingProvider:
    """Scriptable stand-in — an Exception entry is raised instead of returned, same convention
    as tests/services/conftest.py's FakeProvider for the LLM service."""

    def __init__(self, name: str, responses: list[Any] | None = None) -> None:
        self.name = name
        self.responses: list[Any] = responses or []
        self.calls: list[SourcingQuery] = []

    async def search(self, query: SourcingQuery) -> SourcingResult:
        self.calls.append(query)
        if not self.responses:
            raise AssertionError(f"FakeSourcingProvider({self.name}) ran out of responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, SourcingResult)
        return item

    async def aclose(self) -> None:
        return None


def _settings(**overrides: Any) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        **overrides,
    )


def _result(provider: str) -> SourcingResult:
    return SourcingResult(provider=provider, candidates=[_CANDIDATE])


# --------------------------------------------------------------------- provider selection


async def test_uses_configured_provider() -> None:
    pdl = FakeSourcingProvider("pdl", [_result("pdl")])
    fixtures = FakeSourcingProvider("fixtures", [_result("fixtures")])
    service = SourcingService(
        providers={"pdl": pdl, "fixtures": fixtures},
        settings=_settings(sourcing_provider="pdl"),
    )

    result = await service.search(SourcingQuery())

    assert result.provider == "pdl"
    assert len(pdl.calls) == 1
    assert len(fixtures.calls) == 0


async def test_missing_provider_falls_back_to_fixtures() -> None:
    fixtures = FakeSourcingProvider("fixtures", [_result("fixtures")])
    service = SourcingService(
        providers={"fixtures": fixtures}, settings=_settings(sourcing_provider="pdl")
    )

    result = await service.search(SourcingQuery())

    assert result.provider == "fixtures"


# ------------------------------------------------------------------------------ fallback


async def test_auth_error_falls_back_to_fixtures() -> None:
    pdl = FakeSourcingProvider("pdl", [SourcingAuthError("bad key")])
    fixtures = FakeSourcingProvider("fixtures", [_result("fixtures")])
    service = SourcingService(
        providers={"pdl": pdl, "fixtures": fixtures},
        settings=_settings(sourcing_provider="pdl"),
    )

    result = await service.search(SourcingQuery())

    assert result.provider == "fixtures"
    assert len(fixtures.calls) == 1


async def test_quota_error_falls_back_to_fixtures() -> None:
    pdl = FakeSourcingProvider("pdl", [SourcingQuotaExceeded("out of credits")])
    fixtures = FakeSourcingProvider("fixtures", [_result("fixtures")])
    service = SourcingService(
        providers={"pdl": pdl, "fixtures": fixtures},
        settings=_settings(sourcing_provider="pdl"),
    )

    result = await service.search(SourcingQuery())

    assert result.provider == "fixtures"


# --------------------------------------------------------------------------------- caching


async def test_second_search_is_served_from_cache(db_session: AsyncSession) -> None:
    pdl = FakeSourcingProvider("pdl", [_result("pdl")])
    service = SourcingService(providers={"pdl": pdl}, settings=_settings(sourcing_provider="pdl"))
    query = SourcingQuery(titles=["Delivery Rider"])

    first = await service.search(query, session=db_session)
    await db_session.flush()
    assert first.cached is False

    second = await service.search(query, session=db_session)

    assert second.cached is True
    assert second.candidates[0].full_name == "Test Candidate"
    assert len(pdl.calls) == 1  # provider never called a second time


async def test_cache_key_differs_by_provider_query_and_limit() -> None:
    base = SourcingQuery(titles=["a"], limit=10)
    different_limit = SourcingQuery(titles=["a"], limit=5)
    different_query = SourcingQuery(titles=["b"], limit=10)

    assert sourcing_cache_key("pdl", base) != sourcing_cache_key("fixtures", base)
    assert sourcing_cache_key("pdl", base) != sourcing_cache_key("pdl", different_limit)
    assert sourcing_cache_key("pdl", base) != sourcing_cache_key("pdl", different_query)


async def test_empty_result_is_not_cached(db_session: AsyncSession) -> None:
    """An empty result never spent a collect credit, so there's nothing the cache protects by
    keeping it — and keeping it would permanently hide candidates a retry could still find."""
    pdl = FakeSourcingProvider(
        "pdl", [SourcingResult(provider="pdl", candidates=[]), _result("pdl")]
    )
    service = SourcingService(providers={"pdl": pdl}, settings=_settings(sourcing_provider="pdl"))
    query = SourcingQuery(titles=["Delivery Rider"])

    first = await service.search(query, session=db_session)
    await db_session.flush()
    assert first.cached is False
    assert first.candidates == []

    second = await service.search(query, session=db_session)

    assert second.cached is False
    assert len(second.candidates) == 1
    assert len(pdl.calls) == 2  # provider called again — the empty result was never cached


async def test_no_session_means_no_caching() -> None:
    pdl = FakeSourcingProvider("pdl", [_result("pdl"), _result("pdl")])
    service = SourcingService(providers={"pdl": pdl}, settings=_settings(sourcing_provider="pdl"))
    query = SourcingQuery(titles=["Delivery Rider"])

    first = await service.search(query)
    second = await service.search(query)

    assert first.cached is False
    assert second.cached is False
    assert len(pdl.calls) == 2
