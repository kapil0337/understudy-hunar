from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import get_settings

settings = get_settings()

# pool_pre_ping: Neon scales to zero and Render sleeps — without it, the first request after a
# cold start dies on a stale pooled connection and looks like a random 500.
# pool_recycle=300: proactively drop connections older than 5 minutes, ahead of whichever side
# (Neon, Render, or an intermediate proxy) closes idle connections first.
# statement_cache_size=0: asyncpg's own prepared-statement cache breaks against a PgBouncer-style
# transaction-mode pooler (Neon's pooled connection string, used by the Vercel deployment) —
# a statement prepared on one physical connection can get reused against a different one under
# the pool's next transaction, raising "prepared statement does not exist". A direct connection
# doesn't need this, but disabling it there costs nothing worth keeping this branchless for.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"statement_cache_size": 0},
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
