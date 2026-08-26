"""Direct tests of job_runner.drain()/process_one() against a real, separate database
connection — unlike run_pending_background_job (used everywhere else in this suite),
process_one() always opens its own connection via async_session_factory() rather than reusing
whatever session a caller happens to have, so it behaves identically whether called from
app/worker.py's loop or app/api/routes/internal.py's HTTP handler. That's exactly what's under
test here, so this can't use the ordinary db_session fixture's savepoint-isolated session (see
tests/api/test_internal_api.py's module docstring for why) — it points job_runner at its own
NullPool engine bound to TEST_DATABASE_URL instead, and cleans up explicitly since nothing here
rolls back automatically.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.background_job import BackgroundJob
from app.services import job_runner
from tests.conftest import TEST_DATABASE_URL


@pytest.fixture
async def real_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert TEST_DATABASE_URL is not None, "TEST_DATABASE_URL must be set to run this test"
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(job_runner, "async_session_factory", factory)
    try:
        yield factory
    finally:
        async with factory() as session:
            await session.execute(delete(BackgroundJob))
            await session.commit()
        await engine.dispose()


async def test_drain_claims_and_fails_a_job_with_a_bad_payload(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # A fabricated job_id so the handler fails cleanly (ValueError -> FAILED) without needing an
    # LLM configured — this test is about drain() claiming and running a job, not about
    # compile_jd's own logic (already covered in tests/api/test_jobs_api.py).
    async with real_session_factory() as session:
        job = BackgroundJob(kind="compile_jd", payload={"job_id": str(uuid.uuid4()), "raw_jd": "x"})
        session.add(job)
        await session.commit()
        job_id = job.id

    assert await job_runner.drain(1) == 1

    async with real_session_factory() as session:
        refreshed = await session.get(BackgroundJob, job_id)
        assert refreshed is not None
        assert refreshed.status == "FAILED"


async def test_drain_is_a_no_op_on_an_empty_queue(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await job_runner.drain(5) == 0


async def test_drain_respects_the_max_jobs_bound(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_session_factory() as session:
        for _ in range(3):
            session.add(
                BackgroundJob(kind="compile_jd", payload={"job_id": str(uuid.uuid4()), "raw_jd": "x"})
            )
        await session.commit()

    assert await job_runner.drain(2) == 2
    assert await job_runner.drain(2) == 1  # the one left over
    assert await job_runner.drain(2) == 0  # queue's empty now
