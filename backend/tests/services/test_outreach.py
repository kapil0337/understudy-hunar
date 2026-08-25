from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.integrations.hunar.client import BASE_URL as HUNAR_BASE_URL
from app.integrations.hunar.client import HunarClient
from app.integrations.hunar.models import (
    CallRecordingWebhook,
    CallResultWebhook,
    CallStatusWebhook,
    CallSummaryWebhook,
)
from app.models.candidate import Candidate
from app.models.enums import CallStatus, Language
from app.models.job import Job
from app.models.outreach import Outreach
from app.services.outreach import (
    BLOCK_DNC,
    BLOCK_NO_CONSENT,
    BLOCK_NO_PHONE,
    BLOCK_NOT_FOUND,
    TERMINAL_STATUSES,
    OutreachError,
    apply_recording_webhook,
    apply_result_webhook,
    apply_status_transition,
    apply_status_webhook,
    apply_summary_webhook,
    build_request_id,
    call_candidates,
    check_call_allowed,
    refresh_outreach,
)
from tests.services.conftest import load_compiled_fixture

FAKE_NUMBER = "+919876543210"
OTHER_NUMBER = "+919876500000"


def _candidate(**overrides: object) -> Candidate:
    defaults: dict[str, object] = {
        "job_id": uuid.uuid4(),
        "source_provider": "fixtures",
        "source_ref": "fx_001",
        "full_name": "Test Candidate",
        "skills": [],
        "raw_payload": {},
    }
    defaults.update(overrides)
    return Candidate(**defaults)


async def _make_job(session: AsyncSession, jd_name: str = "delivery_rider_chennai") -> Job:
    compiled = load_compiled_fixture(jd_name)
    job = Job(title=compiled["role_title"], raw_jd="raw jd text", compiled=compiled)
    session.add(job)
    await session.flush()
    return job


async def _make_candidate(session: AsyncSession, job: Job, **overrides: object) -> Candidate:
    candidate = _candidate(job_id=job.id, **overrides)
    session.add(candidate)
    await session.flush()
    return candidate


def _settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")


# ------------------------------------------------------------------------------- check_call_allowed


def test_dnc_blocks_even_with_consent() -> None:
    candidate = _candidate(dnc=True, phone_e164=FAKE_NUMBER, consent_recorded_at=datetime.now(UTC))
    assert check_call_allowed(candidate, set()) == BLOCK_DNC


def test_missing_phone_blocks() -> None:
    candidate = _candidate(phone_e164=None)
    assert check_call_allowed(candidate, set()) == BLOCK_NO_PHONE


def test_no_consent_and_not_demo_allowed_blocks() -> None:
    candidate = _candidate(phone_e164=FAKE_NUMBER, consent_recorded_at=None)
    assert check_call_allowed(candidate, set()) == BLOCK_NO_CONSENT


def test_demo_allowed_number_bypasses_consent() -> None:
    candidate = _candidate(phone_e164=FAKE_NUMBER, consent_recorded_at=None)
    assert check_call_allowed(candidate, {FAKE_NUMBER}) is None


def test_consent_recorded_allows_call() -> None:
    candidate = _candidate(phone_e164=FAKE_NUMBER, consent_recorded_at=datetime.now(UTC))
    assert check_call_allowed(candidate, set()) is None


# ---------------------------------------------------------------------------- build_request_id


def test_request_id_matches_pattern_and_is_short() -> None:
    request_id = build_request_id(uuid.uuid4(), uuid.uuid4(), 1)
    assert len(request_id) <= 64
    assert re.match(r"^[A-Za-z0-9_.-]{1,64}$", request_id)


def test_request_id_includes_attempt() -> None:
    job_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    assert build_request_id(job_id, candidate_id, 1) != build_request_id(job_id, candidate_id, 2)


# ------------------------------------------------------------------------- apply_status_transition


def _outreach(status: CallStatus = CallStatus.NOT_STARTED) -> Outreach:
    return Outreach(
        candidate_id=uuid.uuid4(),
        agent_version_id=uuid.uuid4(),
        request_id="job00000000-cand00000000-a1",
        status=status,
        lifecycle_status="QUEUED",
    )


def test_forward_transition_applies() -> None:
    outreach = _outreach(CallStatus.INITIATED)
    assert apply_status_transition(outreach, CallStatus.RINGING) is True
    assert outreach.status == CallStatus.RINGING


def test_backward_transition_rejected() -> None:
    outreach = _outreach(CallStatus.IN_PROGRESS)
    assert apply_status_transition(outreach, CallStatus.RINGING) is False
    assert outreach.status == CallStatus.IN_PROGRESS


def test_completed_never_regresses_to_ringing() -> None:
    outreach = _outreach(CallStatus.COMPLETED)
    assert apply_status_transition(outreach, CallStatus.RINGING) is False
    assert outreach.status == CallStatus.COMPLETED


def test_terminal_status_is_sticky_against_another_terminal_status() -> None:
    outreach = _outreach(CallStatus.FAILED)
    assert apply_status_transition(outreach, CallStatus.COMPLETED) is False
    assert outreach.status == CallStatus.FAILED


def test_all_terminal_statuses_covered() -> None:
    assert {
        CallStatus.COMPLETED,
        CallStatus.NOT_CONNECTED,
        CallStatus.CANCELLED,
        CallStatus.FAILED,
    } == TERMINAL_STATUSES


# ---------------------------------------------------------------------- apply_*_webhook helpers


def test_apply_status_webhook_sets_detail_fields() -> None:
    outreach = _outreach(CallStatus.INITIATED)
    payload = CallStatusWebhook.model_validate(
        {
            "status": "IN_PROGRESS",
            "lifecycle_status": "DIALING",
            "answered_by": "HUMAN",
            "engagement_status": "ENGAGED",
            "duration_seconds": 12,
        }
    )
    assert apply_status_webhook(outreach, payload) is True
    assert outreach.status == CallStatus.IN_PROGRESS
    assert outreach.lifecycle_status == "DIALING"
    assert outreach.answered_by == "HUMAN"
    assert outreach.duration_seconds == 12


def test_apply_status_webhook_gates_detail_on_stale_status() -> None:
    """A status webhook that cannot move the row forward must not leak its detail either."""
    outreach = _outreach(CallStatus.COMPLETED)
    payload = CallStatusWebhook.model_validate({"status": "RINGING", "lifecycle_status": "STALE"})
    assert apply_status_webhook(outreach, payload) is False
    assert outreach.lifecycle_status == "QUEUED"


def test_apply_recording_webhook() -> None:
    outreach = _outreach()
    payload = CallRecordingWebhook.model_validate(
        {"recording_url": "https://example.invalid/r.mp3", "duration_seconds": 90}
    )
    apply_recording_webhook(outreach, payload)
    assert outreach.recording_url == "https://example.invalid/r.mp3"
    assert outreach.duration_seconds == 90


def test_apply_result_webhook() -> None:
    outreach = _outreach()
    payload = CallResultWebhook.model_validate({"result": {"interested": True}})
    apply_result_webhook(outreach, payload)
    assert outreach.result == {"interested": True}


def test_apply_summary_webhook() -> None:
    outreach = _outreach()
    payload = CallSummaryWebhook.model_validate({"summary": "Candidate is interested."})
    apply_summary_webhook(outreach, payload)
    assert outreach.call_summary == "Candidate is interested."


# --------------------------------------------------------------------------------- call_candidates


async def _hunar_client() -> HunarClient:
    transport = httpx.AsyncClient(verify=False)  # noqa: S501
    return HunarClient("test-key", client=transport)


@respx.mock
async def test_call_candidates_happy_path(db_session: AsyncSession) -> None:
    job = await _make_job(db_session)
    candidate = await _make_candidate(
        db_session,
        job,
        phone_e164=FAKE_NUMBER,
        consent_recorded_at=datetime.now(UTC),
        preferred_language=Language.ENGLISH,
    )

    respx.post(f"{HUNAR_BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json={"id": "agt_1", "name": "Test Agent"})
    )
    respx.get(f"{HUNAR_BASE_URL}agents/agt_1/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "agt_1",
                "name": "Test Agent",
                "custom_variables": ["callee_name", "role_title", "role_location"],
            },
        )
    )
    respx.post(f"{HUNAR_BASE_URL}calls/").mock(
        return_value=httpx.Response(200, json={"id": "cal_1", "status": "NOT_STARTED"})
    )

    async with await _hunar_client() as client:
        summary = await call_candidates(
            db_session, job.id, [candidate.id], client=client, settings=_settings()
        )

    assert summary.blocked == []
    assert len(summary.queued) == 1
    assert summary.queued[0].candidate_id == candidate.id
    assert summary.queued[0].hunar_call_id == "cal_1"
    assert summary.versions_used == {"ENGLISH": summary.versions_used["ENGLISH"]}
    assert summary.estimated_minutes > 0

    row = await db_session.get(Outreach, summary.queued[0].outreach_id)
    assert row is not None
    assert row.request_id == summary.queued[0].request_id
    assert row.status == CallStatus.NOT_STARTED


@respx.mock
async def test_call_candidates_reuses_already_published_version(db_session: AsyncSession) -> None:
    """Lazy publishing: a version already published for this (job, language) must not trigger a
    second create_agent call."""
    job = await _make_job(db_session)
    candidate = await _make_candidate(
        db_session,
        job,
        phone_e164=FAKE_NUMBER,
        consent_recorded_at=datetime.now(UTC),
        preferred_language=Language.ENGLISH,
    )

    create_route = respx.post(f"{HUNAR_BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json={"id": "agt_1", "name": "Test Agent"})
    )
    respx.get(f"{HUNAR_BASE_URL}agents/agt_1/").mock(
        return_value=httpx.Response(
            200, json={"id": "agt_1", "name": "Test Agent", "custom_variables": ["callee_name"]}
        )
    )
    respx.post(f"{HUNAR_BASE_URL}calls/").mock(
        return_value=httpx.Response(200, json={"id": "cal_1", "status": "NOT_STARTED"})
    )

    async with await _hunar_client() as client:
        await call_candidates(
            db_session, job.id, [candidate.id], client=client, settings=_settings()
        )
        assert create_route.call_count == 1

        candidate2 = await _make_candidate(
            db_session,
            job,
            phone_e164=OTHER_NUMBER,
            consent_recorded_at=datetime.now(UTC),
            preferred_language=Language.ENGLISH,
        )
        await call_candidates(
            db_session, job.id, [candidate2.id], client=client, settings=_settings()
        )

    assert create_route.call_count == 1  # still just once — the version was reused


@respx.mock
async def test_call_candidates_blocks_dnc_no_phone_no_consent_and_not_found(
    db_session: AsyncSession,
) -> None:
    job = await _make_job(db_session)
    dnc_candidate = await _make_candidate(db_session, job, dnc=True, phone_e164=FAKE_NUMBER)
    no_phone_candidate = await _make_candidate(db_session, job, phone_e164=None)
    no_consent_candidate = await _make_candidate(
        db_session, job, phone_e164=OTHER_NUMBER, consent_recorded_at=None
    )
    missing_id = uuid.uuid4()

    async with await _hunar_client() as client:
        summary = await call_candidates(
            db_session,
            job.id,
            [dnc_candidate.id, no_phone_candidate.id, no_consent_candidate.id, missing_id],
            client=client,
            settings=_settings(),
        )

    assert summary.queued == []
    reasons = {b.candidate_id: b.reason for b in summary.blocked}
    assert reasons[dnc_candidate.id] == BLOCK_DNC
    assert reasons[no_phone_candidate.id] == BLOCK_NO_PHONE
    assert reasons[no_consent_candidate.id] == BLOCK_NO_CONSENT
    assert reasons[missing_id] == BLOCK_NOT_FOUND


@respx.mock
async def test_call_candidates_unknown_custom_variable_blocks_just_that_language(
    db_session: AsyncSession,
) -> None:
    job = await _make_job(db_session)
    candidate = await _make_candidate(
        db_session,
        job,
        phone_e164=FAKE_NUMBER,
        consent_recorded_at=datetime.now(UTC),
        preferred_language=Language.ENGLISH,
    )

    respx.post(f"{HUNAR_BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json={"id": "agt_1", "name": "Test Agent"})
    )
    respx.get(f"{HUNAR_BASE_URL}agents/agt_1/").mock(
        return_value=httpx.Response(
            200,
            json={"id": "agt_1", "name": "Test Agent", "custom_variables": ["something_unknown"]},
        )
    )

    async with await _hunar_client() as client:
        summary = await call_candidates(
            db_session, job.id, [candidate.id], client=client, settings=_settings()
        )

    assert summary.queued == []
    assert len(summary.blocked) == 1
    assert summary.blocked[0].candidate_id == candidate.id
    assert "something_unknown" in summary.blocked[0].reason


async def test_call_candidates_raises_for_uncompiled_job(db_session: AsyncSession) -> None:
    job = Job(title="x", raw_jd="raw", compiled=None)
    db_session.add(job)
    await db_session.flush()

    async with await _hunar_client() as client:
        with pytest.raises(OutreachError):
            await call_candidates(db_session, job.id, [], client=client, settings=_settings())


# ------------------------------------------------------------------------------- refresh_outreach


async def _make_agent_version(session: AsyncSession, job_id: uuid.UUID, version_no: int) -> Any:
    from app.models.agent_version import AgentVersion
    from app.models.enums import AgentVersionOrigin

    version = AgentVersion(
        job_id=job_id,
        version_no=version_no,
        language=Language.ENGLISH,
        voice_persona="NEHA",
        persona_name="Neha",
        agent_prompt="p",
        objective="o",
        introduction="i",
        result_prompt="r",
        result_schema={},
        hunar_agent_id="agt_1",
        origin=AgentVersionOrigin.COMPILED,
    )
    session.add(version)
    await session.flush()
    return version


async def _make_outreach(
    session: AsyncSession,
    candidate: Candidate,
    *,
    status: CallStatus,
    hunar_call_id: str | None,
    updated_at: datetime,
    version_no: int = 1,
) -> Outreach:
    version = await _make_agent_version(session, candidate.job_id, version_no)

    outreach = Outreach(
        candidate_id=candidate.id,
        agent_version_id=version.id,
        hunar_call_id=hunar_call_id,
        request_id=f"job-{candidate.id.hex[:8]}-a1",
        status=status,
        lifecycle_status="QUEUED",
    )
    session.add(outreach)
    await session.flush()
    outreach.updated_at = updated_at
    session.add(outreach)
    await session.flush()
    return outreach


@respx.mock
async def test_refresh_outreach_updates_stale_non_terminal_rows(db_session: AsyncSession) -> None:
    job = await _make_job(db_session)
    candidate = await _make_candidate(db_session, job)
    stale = datetime.now(UTC) - timedelta(seconds=30)
    await _make_outreach(
        db_session, candidate, status=CallStatus.RINGING, hunar_call_id="cal_1", updated_at=stale
    )

    respx.get(f"{HUNAR_BASE_URL}calls/cal_1/").mock(
        return_value=httpx.Response(200, json={"id": "cal_1", "status": "COMPLETED"})
    )

    async with await _hunar_client() as client:
        refreshed = await refresh_outreach(db_session, job.id, client=client)

    assert len(refreshed) == 1
    assert refreshed[0].status == CallStatus.COMPLETED


@respx.mock
async def test_refresh_outreach_skips_recently_updated_rows(db_session: AsyncSession) -> None:
    job = await _make_job(db_session)
    candidate = await _make_candidate(db_session, job)
    fresh = datetime.now(UTC) - timedelta(seconds=2)
    await _make_outreach(
        db_session, candidate, status=CallStatus.RINGING, hunar_call_id="cal_1", updated_at=fresh
    )

    async with await _hunar_client() as client:
        refreshed = await refresh_outreach(db_session, job.id, client=client)

    assert refreshed == []


@respx.mock
async def test_refresh_outreach_skips_terminal_rows(db_session: AsyncSession) -> None:
    job = await _make_job(db_session)
    candidate = await _make_candidate(db_session, job)
    stale = datetime.now(UTC) - timedelta(seconds=30)
    await _make_outreach(
        db_session, candidate, status=CallStatus.COMPLETED, hunar_call_id="cal_1", updated_at=stale
    )

    async with await _hunar_client() as client:
        refreshed = await refresh_outreach(db_session, job.id, client=client)

    assert refreshed == []


@respx.mock
async def test_refresh_outreach_caps_batch_at_ten(db_session: AsyncSession) -> None:
    job = await _make_job(db_session)
    stale = datetime.now(UTC) - timedelta(seconds=30)
    respx.get(url__regex=r".*/calls/cal_\d+/").mock(
        return_value=httpx.Response(200, json={"id": "cal_x", "status": "COMPLETED"})
    )

    for i in range(12):
        candidate = await _make_candidate(db_session, job)
        await _make_outreach(
            db_session,
            candidate,
            status=CallStatus.RINGING,
            hunar_call_id=f"cal_{i}",
            updated_at=stale,
            version_no=i + 1,
        )

    async with await _hunar_client() as client:
        refreshed = await refresh_outreach(db_session, job.id, client=client)

    assert len(refreshed) == 10
