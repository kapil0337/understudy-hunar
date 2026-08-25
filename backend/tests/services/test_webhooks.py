from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.agent_version import AgentVersion
from app.models.candidate import Candidate
from app.models.enums import AgentVersionOrigin, CallStatus, Language
from app.models.job import Job
from app.models.outreach import Outreach
from app.models.webhook_event import WebhookEvent
from app.services.webhooks import process_webhook
from tests.integrations.conftest import load_fixture

API_KEY = "test-key-not-a-real-credential"
# The captured fixtures use this request_id/call_id pair — see
# tests/fixtures/hunar/webhook_call_*.json.
FIXTURE_REQUEST_ID = "job1234-cand5678-a1"
FIXTURE_CALL_ID = "cal_00000000000000000000000001"


def _sign(api_key: str, timestamp: str, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return base64.b64encode(hmac.new(api_key.encode(), message, hashlib.sha256).digest()).decode()


def _fresh_timestamp() -> str:
    return str(int(time.time()))


async def _make_outreach(
    session: AsyncSession,
    *,
    request_id: str = FIXTURE_REQUEST_ID,
    hunar_call_id: str | None = FIXTURE_CALL_ID,
    status: CallStatus = CallStatus.INITIATED,
) -> Outreach:
    job = Job(title="x", raw_jd="raw jd text")
    session.add(job)
    await session.flush()

    candidate = Candidate(
        job_id=job.id,
        source_provider="fixtures",
        source_ref="fx_001",
        full_name="Test Candidate",
        skills=[],
        raw_payload={},
    )
    session.add(candidate)
    await session.flush()

    version = AgentVersion(
        job_id=job.id,
        version_no=1,
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

    outreach = Outreach(
        candidate_id=candidate.id,
        agent_version_id=version.id,
        hunar_call_id=hunar_call_id,
        request_id=request_id,
        status=status,
        lifecycle_status="QUEUED",
    )
    session.add(outreach)
    await session.flush()
    return outreach


async def _get_outreach(session: AsyncSession, request_id: str = FIXTURE_REQUEST_ID) -> Outreach:
    return (
        await session.execute(select(Outreach).where(col(Outreach.request_id) == request_id))
    ).scalar_one()


async def _process(
    session: AsyncSession,
    kind: Any,
    payload: dict[str, Any],
    *,
    valid_signature: bool = True,
) -> Any:
    raw_body = json.dumps(payload).encode()
    timestamp = _fresh_timestamp()
    signature = _sign(API_KEY if valid_signature else "wrong-key", timestamp, raw_body)
    return await process_webhook(
        session,
        kind,
        api_key=API_KEY,
        timestamp=timestamp,
        signature_header=signature,
        raw_body=raw_body,
    )


# --------------------------------------------------------------------------------- signature


async def test_invalid_signature_is_persisted_and_rejected(db_session: AsyncSession) -> None:
    payload = load_fixture("webhook_call_status.json")
    outcome = await _process(db_session, "status", payload, valid_signature=False)

    assert outcome.signature_valid is False
    assert outcome.resolved is False
    assert outcome.applied is False

    event = await db_session.get(WebhookEvent, outcome.event_id)
    assert event is not None
    assert event.signature_valid is False
    assert event.raw_payload == payload


async def test_valid_signature_but_unresolved_id_is_still_accepted(
    db_session: AsyncSession,
) -> None:
    payload = load_fixture("webhook_call_status.json")  # no matching outreach row exists
    outcome = await _process(db_session, "status", payload)

    assert outcome.signature_valid is True
    assert outcome.resolved is False
    assert outcome.applied is False

    event = await db_session.get(WebhookEvent, outcome.event_id)
    assert event is not None
    assert event.signature_valid is True


# ------------------------------------------------------------------------------------ dispatch


async def test_status_webhook_updates_outreach(db_session: AsyncSession) -> None:
    await _make_outreach(db_session, status=CallStatus.INITIATED)
    payload = load_fixture("webhook_call_status.json")

    outcome = await _process(db_session, "status", payload)

    assert outcome.resolved is True
    assert outcome.applied is True
    row = await _get_outreach(db_session)
    assert row.status == CallStatus.IN_PROGRESS
    assert row.lifecycle_status == "DIALING"
    assert row.answered_by == "HUMAN"
    assert row.duration_seconds == 12


async def test_recording_webhook_updates_outreach(db_session: AsyncSession) -> None:
    await _make_outreach(db_session)
    payload = load_fixture("webhook_call_recording.json")

    outcome = await _process(db_session, "recording", payload)

    assert outcome.applied is True
    row = await _get_outreach(db_session)
    assert row.recording_url == payload["recording_url"]
    assert row.duration_seconds == payload["duration_seconds"]


async def test_result_webhook_updates_outreach(db_session: AsyncSession) -> None:
    await _make_outreach(db_session)
    payload = load_fixture("webhook_call_result.json")

    outcome = await _process(db_session, "result", payload)

    assert outcome.applied is True
    row = await _get_outreach(db_session)
    assert row.result == payload["result"]


async def test_summary_webhook_updates_outreach(db_session: AsyncSession) -> None:
    await _make_outreach(db_session)
    payload = load_fixture("webhook_call_summary.json")

    outcome = await _process(db_session, "summary", payload)

    assert outcome.applied is True
    row = await _get_outreach(db_session)
    assert row.call_summary == payload["summary"]


# ------------------------------------------------------------------------------ resolution


async def test_resolves_by_hunar_call_id_when_request_id_does_not_match(
    db_session: AsyncSession,
) -> None:
    await _make_outreach(db_session, request_id="job-other-a1", hunar_call_id=FIXTURE_CALL_ID)
    payload = load_fixture("webhook_call_status.json")  # request_id differs, call_id matches

    outcome = await _process(db_session, "status", payload)

    assert outcome.resolved is True
    assert outcome.applied is True


# ---------------------------------------------------------------------------- idempotency


async def test_duplicate_status_webhook_is_not_reapplied(db_session: AsyncSession) -> None:
    await _make_outreach(db_session, status=CallStatus.INITIATED)
    payload = load_fixture("webhook_call_status.json")

    first = await _process(db_session, "status", payload)
    second = await _process(db_session, "status", payload)

    assert first.duplicate is False
    assert first.applied is True
    assert second.duplicate is True
    assert second.applied is False


async def test_duplicate_recording_webhook_is_not_reapplied(db_session: AsyncSession) -> None:
    await _make_outreach(db_session)
    payload = load_fixture("webhook_call_recording.json")

    first = await _process(db_session, "recording", payload)
    second = await _process(db_session, "recording", payload)

    assert first.duplicate is False
    assert second.duplicate is True


# ------------------------------------------------------------------------- status precedence


async def test_out_of_order_status_does_not_regress(db_session: AsyncSession) -> None:
    """A different (non-duplicate) status that would move the row backward is rejected by
    precedence, distinct from an exact resend caught by the idempotency check."""
    await _make_outreach(db_session, status=CallStatus.IN_PROGRESS)

    stale_payload = dict(load_fixture("webhook_call_status.json"))
    stale_payload["status"] = "RINGING"

    outcome = await _process(db_session, "status", stale_payload)

    assert outcome.resolved is True
    assert outcome.duplicate is False  # different status value, not a resend
    assert outcome.applied is False  # but precedence still refuses it

    row = await _get_outreach(db_session)
    assert row.status == CallStatus.IN_PROGRESS


async def test_webhook_event_is_always_persisted_even_when_not_applied(
    db_session: AsyncSession,
) -> None:
    await _make_outreach(db_session, status=CallStatus.COMPLETED)
    payload = dict(load_fixture("webhook_call_status.json"))
    payload["status"] = "RINGING"

    before = (await db_session.execute(select(func.count()).select_from(WebhookEvent))).scalar_one()
    await _process(db_session, "status", payload)
    after = (await db_session.execute(select(func.count()).select_from(WebhookEvent))).scalar_one()

    assert after == before + 1


def test_fixture_request_id_matches_module_constant() -> None:
    payload = load_fixture("webhook_call_status.json")
    assert payload["request_id"] == FIXTURE_REQUEST_ID
    assert payload["call_id"] == FIXTURE_CALL_ID
