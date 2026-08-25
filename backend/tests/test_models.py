from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models import AgentVersion, Candidate, Job, Outreach
from app.models.enums import AgentVersionOrigin, CallStatus, Language, VoicePersona


def make_job(title: str = "Backend Engineer") -> Job:
    return Job(title=title, raw_jd="We need a backend engineer.", compiled={"skills": ["python"]})


def make_agent_version(job_id: uuid.UUID, *, version_no: int = 1) -> AgentVersion:
    return AgentVersion(
        job_id=job_id,
        version_no=version_no,
        language=Language.ENGLISH,
        voice_persona=VoicePersona.NEHA,
        persona_name="Neha",
        agent_prompt="You are a recruiter.",
        objective="Screen the candidate.",
        introduction="Hi, calling about a role.",
        result_prompt="Summarise the screen.",
        result_schema={"type": "object"},
        origin=AgentVersionOrigin.COMPILED,
    )


def make_candidate(job_id: uuid.UUID) -> Candidate:
    return Candidate(
        job_id=job_id,
        source_provider="fixture",
        source_ref="fixture-1",
        full_name="Test Candidate",
        raw_payload={"source": "fixture"},
    )


async def test_job_round_trips_jsonb_and_utc_timestamp(db_session: AsyncSession) -> None:
    job = make_job()
    db_session.add(job)
    await db_session.flush()

    stored = (await db_session.execute(select(Job).where(col(Job.id) == job.id))).scalar_one()

    assert stored.compiled == {"skills": ["python"]}
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset() == timedelta(0)


async def test_agent_version_unique_per_job_language_version(db_session: AsyncSession) -> None:
    job = make_job()
    db_session.add(job)
    await db_session.flush()

    db_session.add(make_agent_version(job.id, version_no=1))
    await db_session.flush()

    db_session.add(make_agent_version(job.id, version_no=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_agent_version_allows_next_version_number(db_session: AsyncSession) -> None:
    job = make_job()
    db_session.add(job)
    await db_session.flush()

    db_session.add(make_agent_version(job.id, version_no=1))
    db_session.add(make_agent_version(job.id, version_no=2))
    await db_session.flush()

    versions = (
        (await db_session.execute(select(AgentVersion).where(col(AgentVersion.job_id) == job.id)))
        .scalars()
        .all()
    )
    assert {version.version_no for version in versions} == {1, 2}


async def _seed_outreach_prerequisites(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    job = make_job()
    db_session.add(job)
    await db_session.flush()

    agent_version = make_agent_version(job.id)
    candidate = make_candidate(job.id)
    db_session.add(agent_version)
    db_session.add(candidate)
    await db_session.flush()
    return candidate.id, agent_version.id


async def test_outreach_accepts_valid_request_id(db_session: AsyncSession) -> None:
    candidate_id, agent_version_id = await _seed_outreach_prerequisites(db_session)

    outreach = Outreach(
        candidate_id=candidate_id,
        agent_version_id=agent_version_id,
        request_id="job1234-cand5678-a1",
        lifecycle_status="PENDING",
    )
    db_session.add(outreach)
    await db_session.flush()

    assert outreach.status is CallStatus.NOT_STARTED
    assert outreach.is_simulated is False


# request_id is guarded on two independent levels, which surface as different errors:
# characters outside [A-Za-z0-9_.-] violate the CHECK constraint (IntegrityError), while
# anything over 64 characters is refused by the varchar(64) column type before the CHECK is
# ever evaluated (DBAPIError). Asserting the specific error keeps each level honest.
@pytest.mark.parametrize("bad_request_id", ["has spaces", "has/slash", "has:colon", "has#hash"])
async def test_outreach_rejects_malformed_request_id(
    db_session: AsyncSession, bad_request_id: str
) -> None:
    candidate_id, agent_version_id = await _seed_outreach_prerequisites(db_session)

    db_session.add(
        Outreach(
            candidate_id=candidate_id,
            agent_version_id=agent_version_id,
            request_id=bad_request_id,
            lifecycle_status="PENDING",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_outreach_rejects_overlong_request_id(db_session: AsyncSession) -> None:
    candidate_id, agent_version_id = await _seed_outreach_prerequisites(db_session)

    db_session.add(
        Outreach(
            candidate_id=candidate_id,
            agent_version_id=agent_version_id,
            request_id="x" * 65,
            lifecycle_status="PENDING",
        )
    )
    with pytest.raises(DBAPIError):
        await db_session.flush()


# The next two tests are a pair: both commit a row with the same unique request_id. They pass
# only if db_session really does roll back — if anything leaked between tests, the second would
# fail on the unique constraint. Committing (not just flushing) also exercises
# join_transaction_mode="create_savepoint".
async def test_rollback_isolation_first_writer(db_session: AsyncSession) -> None:
    candidate_id, agent_version_id = await _seed_outreach_prerequisites(db_session)
    db_session.add(
        Outreach(
            candidate_id=candidate_id,
            agent_version_id=agent_version_id,
            request_id="isolation-probe-a1",
            lifecycle_status="PENDING",
        )
    )
    await db_session.commit()

    assert await _count_probe_rows(db_session) == 1


async def test_rollback_isolation_second_writer(db_session: AsyncSession) -> None:
    candidate_id, agent_version_id = await _seed_outreach_prerequisites(db_session)
    db_session.add(
        Outreach(
            candidate_id=candidate_id,
            agent_version_id=agent_version_id,
            request_id="isolation-probe-a1",
            lifecycle_status="PENDING",
        )
    )
    await db_session.commit()

    assert await _count_probe_rows(db_session) == 1


async def _count_probe_rows(db_session: AsyncSession) -> int:
    rows = (
        (
            await db_session.execute(
                select(Outreach).where(col(Outreach.request_id) == "isolation-probe-a1")
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


async def test_outreach_request_id_is_unique(db_session: AsyncSession) -> None:
    candidate_id, agent_version_id = await _seed_outreach_prerequisites(db_session)

    for _ in range(2):
        db_session.add(
            Outreach(
                candidate_id=candidate_id,
                agent_version_id=agent_version_id,
                request_id="job1234-cand5678-a1",
                lifecycle_status="PENDING",
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()
