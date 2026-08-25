"""Candidate sourcing: picks a provider, serves from provider_cache when possible, and falls
back to fixtures on a PDL auth or quota error.

Caching here exists for the same reason as app/services/llm.py's cache: PDL's free tier is 100
credits/month, so a repeated search during a demo must not spend more of them. Every response —
from either provider — is cached under sha256(provider, query, limit), and the result carries
`cached` so the UI can show a "cached" badge and prove no credits were burned.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.settings import Settings, get_settings
from app.integrations.sourcing.base import (
    SourcedCandidate,
    SourcingAuthError,
    SourcingProvider,
    SourcingQuery,
    SourcingQuotaExceeded,
    SourcingResult,
)
from app.integrations.sourcing.fixtures import FixtureProvider
from app.integrations.sourcing.pdl import PDLProvider
from app.models.cache import ProviderCache

logger = structlog.get_logger()


def sourcing_cache_key(provider: str, query: SourcingQuery) -> str:
    """sha256(provider, query, limit) per CLAUDE.md's caching convention. `limit` is included
    explicitly even though it is already a SourcingQuery field, so the key's shape documents the
    three inputs it is defined over."""
    payload = json.dumps(
        {
            "provider": provider,
            "query": query.model_dump(mode="json", exclude={"limit"}),
            "limit": query.limit,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class SourcingService:
    def __init__(
        self,
        *,
        providers: dict[str, SourcingProvider] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._providers = providers if providers is not None else _build_providers(self._settings)
        self._fixtures = self._providers.get("fixtures") or FixtureProvider()

    async def search(
        self, query: SourcingQuery, *, session: AsyncSession | None = None
    ) -> SourcingResult:
        provider_name = self._settings.sourcing_provider
        key = sourcing_cache_key(provider_name, query)

        if session is not None:
            cached = await _get_cached(session, key)
            if cached is not None:
                logger.info("sourcing_cache_hit", provider=provider_name, key=key[:12])
                return SourcingResult(
                    provider=cached["provider"],
                    candidates=[SourcedCandidate.model_validate(c) for c in cached["candidates"]],
                    cached=True,
                )

        result = await self._search_with_fallback(provider_name, query)

        if session is not None:
            await _store(session, key, result)

        return result

    async def _search_with_fallback(
        self, provider_name: str, query: SourcingQuery
    ) -> SourcingResult:
        provider = self._providers.get(provider_name)
        if provider is None:
            logger.warning("sourcing_provider_unconfigured", provider=provider_name)
            return await self._fixtures.search(query)

        try:
            return await provider.search(query)
        except (SourcingAuthError, SourcingQuotaExceeded) as exc:
            logger.warning(
                "sourcing_provider_fell_back_to_fixtures",
                provider=provider_name,
                reason=type(exc).__name__,
            )
            return await self._fixtures.search(query)

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()


async def _get_cached(session: AsyncSession, key: str) -> dict[str, Any] | None:
    row = (
        await session.execute(select(ProviderCache).where(col(ProviderCache.key) == key))
    ).scalar_one_or_none()
    return row.response if row is not None else None


async def _store(session: AsyncSession, key: str, result: SourcingResult) -> None:
    # fetched_at is set explicitly: this is a Core-level insert, bypassing the ORM instance
    # construction that would apply the column's default_factory (same fix as
    # jd_compiler._store_compilation and llm.DatabaseLLMCache.set).
    await session.execute(
        pg_insert(ProviderCache)
        .values(
            key=key,
            provider=result.provider,
            response={
                "provider": result.provider,
                "candidates": [c.model_dump(mode="json") for c in result.candidates],
            },
            fetched_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["key"])
    )
    await session.flush()


def _build_providers(settings: Settings) -> dict[str, SourcingProvider]:
    providers: dict[str, SourcingProvider] = {"fixtures": FixtureProvider()}
    if settings.pdl_api_key:
        providers["pdl"] = PDLProvider(settings.pdl_api_key)
    return providers


_default_service: SourcingService | None = None


def get_sourcing_service() -> SourcingService:
    global _default_service
    if _default_service is None:
        _default_service = SourcingService()
    return _default_service


def set_sourcing_service(service: SourcingService | None) -> None:
    """Override (or reset) the default service. Exists for tests and for wiring at startup."""
    global _default_service
    _default_service = service
