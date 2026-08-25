from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command

logger = structlog.get_logger()

# Arbitrary but fixed — must stay constant across deploys, since it's how concurrent instances
# recognize each other's lock. Any 32-bit int works; this one has no special meaning.
_ADVISORY_LOCK_KEY = 8_422_051

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"
_ALEMBIC_SCRIPT_LOCATION = _BACKEND_ROOT / "alembic"


def _upgrade_head() -> None:
    # alembic/env.py does asyncio.run(...) internally, which fails if a loop is already running
    # in this thread — this function must only ever be called via asyncio.to_thread, never
    # directly from the (already async) lifespan.
    config = Config(str(_ALEMBIC_INI))
    # Override rather than trust alembic's own relative-path resolution, which resolves
    # script_location against the process's CWD — not guaranteed to be backend/ here.
    config.set_main_option("script_location", str(_ALEMBIC_SCRIPT_LOCATION))
    command.upgrade(config, "head")


async def run_migrations_with_lock(engine: AsyncEngine) -> None:
    """Runs `alembic upgrade head` under a Postgres advisory lock, so that when multiple app
    instances or workers boot at once (a rolling deploy, several Render dynos), only one of
    them actually migrates while the rest wait — instead of racing on DDL or alembic_version."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        try:
            logger.info("running_migrations")
            await asyncio.to_thread(_upgrade_head)
            logger.info("migrations_complete")
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
