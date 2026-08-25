"""Shared FastAPI dependencies. AsyncSession comes from app.db.session.get_db directly —
nothing route-specific to add there. HunarClient needs a route-specific wrapper because its
absence is sometimes fatal (placing a call, publishing) and sometimes just means "skip this
optional step" (refreshing the board)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import HTTPException, status

from app.core.settings import get_settings
from app.integrations.hunar.client import HunarClient


async def get_hunar_client() -> AsyncIterator[HunarClient]:
    """For routes that cannot proceed without Hunar: publishing, launching calls. 503s clearly
    rather than failing deeper with a confusing error."""
    settings = get_settings()
    if not settings.hunar_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Hunar is not configured (HUNAR_API_KEY missing) — this action needs a real "
            "connection to Hunar.",
        )
    async with HunarClient(settings.hunar_api_key) as client:
        yield client


async def get_optional_hunar_client() -> AsyncIterator[HunarClient | None]:
    """For routes where Hunar is a nice-to-have: the board still reads correctly from whatever
    was last polled or received by webhook, just without a fresh poll this time."""
    settings = get_settings()
    if not settings.hunar_api_key:
        yield None
        return
    async with HunarClient(settings.hunar_api_key) as client:
        yield client
