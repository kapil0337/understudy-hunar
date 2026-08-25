from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_hunar_client, get_optional_hunar_client
from app.db.session import get_db
from app.integrations.hunar.client import HunarClient
from app.main import app

# Not a real key — same fixture-only convention as tests/integrations/conftest.py.
TEST_HUNAR_API_KEY = "test-key-not-a-real-credential"


@pytest.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx.AsyncClient over the app via ASGITransport — NOT Starlette's synchronous
    TestClient, which runs the app in its own background thread/event loop via an anyio portal.
    That thread-hop is fatal here: the test's asyncpg connection (inside `db_session`) is bound
    to THIS test's event loop, and asyncpg refuses to use a connection from any other loop.
    ASGITransport calls the app as a plain coroutine in the caller's own loop, so the same
    session/connection this fixture overrides get_db with is the one the route actually uses.
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def api_client_with_hunar(
    api_client: httpx.AsyncClient,
) -> AsyncIterator[httpx.AsyncClient]:
    """Adds get_hunar_client/get_optional_hunar_client overrides pointing at a real HunarClient
    whose transport respx can intercept — bypasses the HUNAR_API_KEY settings check entirely,
    so tests using this fixture simulate "Hunar is configured" regardless of the environment."""
    async with httpx.AsyncClient(verify=False) as hunar_transport:  # noqa: S501
        client = HunarClient(TEST_HUNAR_API_KEY, client=hunar_transport)

        async def _override_required() -> AsyncIterator[HunarClient]:
            yield client

        async def _override_optional() -> AsyncIterator[HunarClient | None]:
            yield client

        app.dependency_overrides[get_hunar_client] = _override_required
        app.dependency_overrides[get_optional_hunar_client] = _override_optional
        try:
            yield api_client
        finally:
            app.dependency_overrides.pop(get_hunar_client, None)
            app.dependency_overrides.pop(get_optional_hunar_client, None)
