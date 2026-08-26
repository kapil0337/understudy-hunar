from __future__ import annotations

import os

# Set before app.main is imported, since get_settings() runs at import time.
#
# DATABASE_URL is deliberately pointed at an unroutable DSN: no test should ever reach the
# application database. Everything that touches Postgres goes through the `db_session` fixture
# below, which is bound to TEST_DATABASE_URL. If some code path ignores the fixture and opens
# the app engine instead, it fails loudly here rather than quietly mutating a real database.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("ENVIRONMENT", "test")

# Disable Settings' own `.env` file loading before anything constructs one: a developer's real
# backend/.env (with real keys) sitting next to this file would otherwise get picked up whenever
# a test deletes a key from os.environ expecting "absent", since pydantic-settings falls through
# env var -> .env file -> default. Tests control configuration via os.environ/monkeypatch only.
from app.core.settings import Settings as _Settings  # noqa: E402

_Settings.model_config["env_file"] = None

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.main import app  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run if the test database is (or might be) the application database.

    A transactional fixture that rolls back is only safe when it is pointed somewhere
    disposable. Comparing the two DSNs is a cheap guard against the expensive mistake of
    running the suite against real data.
    """
    app_url = os.environ.get("DATABASE_URL")
    if TEST_DATABASE_URL is not None and app_url == TEST_DATABASE_URL:
        raise pytest.UsageError(
            "TEST_DATABASE_URL must not equal DATABASE_URL. The suite writes and rolls back "
            "against TEST_DATABASE_URL and must never point at the application database."
        )


@pytest.fixture
def client() -> TestClient:
    """Note: not used as a context manager, so the app's lifespan (which runs migrations)
    does not fire. Tests that need the schema use `db_session`."""
    return TestClient(app)


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session wrapped in a transaction that is always rolled back, so each test sees a
    clean database and leaves nothing behind.

    join_transaction_mode="create_savepoint" means a `commit()` inside a test resolves to
    releasing a savepoint rather than committing the outer transaction — so code under test
    can commit normally and the rollback here still undoes all of it.
    """
    if TEST_DATABASE_URL is None:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Start the test database with "
            "`docker compose --profile test up -d postgres-test` and run via `make test`."
        )

    # NullPool + a per-test engine: pytest-asyncio gives each test its own event loop, and a
    # pooled connection created on one loop cannot be reused on another.
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                yield session
            finally:
                await session.close()
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        await engine.dispose()
