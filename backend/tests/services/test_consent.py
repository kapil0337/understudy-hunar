from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.integrations.whatsapp.channel import WhatsAppConsentChannel
from app.models.candidate import Candidate
from app.models.job import Job
from app.services.consent import (
    ConsentError,
    ManualConsentChannel,
    build_consent_channel,
    record_consent,
    record_decline,
)

# Not a real number — same fake-Indian-mobile convention used in tests/integrations/test_hunar_client.py.
FAKE_NUMBER = "+919876543210"


async def _make_candidate(session: AsyncSession) -> Candidate:
    job = Job(title="Delivery Rider", raw_jd="raw jd text")
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
    return candidate


# ------------------------------------------------------------------------- ManualConsentChannel


async def test_manual_request_consent_is_not_applicable() -> None:
    channel = ManualConsentChannel()
    job = Job(title="x", raw_jd="raw")
    candidate = Candidate(
        job_id=uuid.uuid4(),
        source_provider="fixtures",
        source_ref="fx_001",
        full_name="Test Candidate",
        skills=[],
        raw_payload={},
    )

    request = await channel.request_consent(candidate, job)

    assert request.status == "not_applicable"
    assert request.channel == "MANUAL"


async def test_manual_handle_inbound_not_implemented() -> None:
    channel = ManualConsentChannel()
    with pytest.raises(NotImplementedError):
        await channel.handle_inbound({})


# ------------------------------------------------------------------------------ record_consent


async def test_record_consent_sets_phone_and_timestamp(db_session: AsyncSession) -> None:
    candidate = await _make_candidate(db_session)

    updated = await record_consent(db_session, candidate.id, FAKE_NUMBER)

    assert updated.phone_e164 == FAKE_NUMBER
    assert updated.consent_recorded_at is not None
    assert updated.consent_channel == "MANUAL"


async def test_record_consent_rejects_invalid_number(db_session: AsyncSession) -> None:
    candidate = await _make_candidate(db_session)

    with pytest.raises(ConsentError):
        await record_consent(db_session, candidate.id, "not-a-number")


async def test_record_consent_unknown_candidate_raises(db_session: AsyncSession) -> None:
    with pytest.raises(ConsentError):
        await record_consent(db_session, uuid.uuid4(), FAKE_NUMBER)


async def test_record_consent_custom_channel(db_session: AsyncSession) -> None:
    candidate = await _make_candidate(db_session)

    updated = await record_consent(db_session, candidate.id, FAKE_NUMBER, channel="WHATSAPP")

    assert updated.consent_channel == "WHATSAPP"


# ------------------------------------------------------------------------------ record_decline


async def test_record_decline_sets_dnc(db_session: AsyncSession) -> None:
    candidate = await _make_candidate(db_session)
    assert candidate.dnc is False

    updated = await record_decline(db_session, candidate.id)

    assert updated.dnc is True


# ------------------------------------------------------------------------- build_consent_channel


def _settings(channel: str) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused", channel=channel
    )


def test_build_consent_channel_defaults_to_manual() -> None:
    assert isinstance(build_consent_channel(_settings("manual")), ManualConsentChannel)


def test_build_consent_channel_whatsapp() -> None:
    assert isinstance(build_consent_channel(_settings("whatsapp")), WhatsAppConsentChannel)
