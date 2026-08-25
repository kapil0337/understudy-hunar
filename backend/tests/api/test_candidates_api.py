from __future__ import annotations

import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job

FAKE_NUMBER = "+919876543210"


async def _make_candidate(session: AsyncSession) -> Candidate:
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
    return candidate


# --------------------------------------------------------------------------------------- patch


async def test_patch_candidate_updates_dnc(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    candidate = await _make_candidate(db_session)

    resp = await api_client.patch(f"/candidates/{candidate.id}", json={"dnc": True})
    assert resp.status_code == 200
    assert resp.json()["dnc"] is True
    assert resp.json()["consent_recorded_at"] is None  # PATCH never sets consent


async def test_patch_candidate_normalises_phone_to_e164(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    candidate = await _make_candidate(db_session)

    resp = await api_client.patch(f"/candidates/{candidate.id}", json={"phone_e164": FAKE_NUMBER})
    assert resp.status_code == 200
    assert resp.json()["phone_e164"] == FAKE_NUMBER


async def test_patch_candidate_rejects_invalid_phone(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    candidate = await _make_candidate(db_session)

    resp = await api_client.patch(
        f"/candidates/{candidate.id}", json={"phone_e164": "not-a-number"}
    )
    assert resp.status_code == 422


async def test_patch_unknown_candidate_404(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.patch(f"/candidates/{uuid.uuid4()}", json={"dnc": True})
    assert resp.status_code == 404


# ------------------------------------------------------------------------------------- consent


async def test_record_consent_sets_phone_and_timestamp(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    candidate = await _make_candidate(db_session)

    resp = await api_client.post(
        f"/candidates/{candidate.id}/consent", json={"phone_e164": FAKE_NUMBER}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["phone_e164"] == FAKE_NUMBER
    assert body["consent_recorded_at"] is not None
    assert body["consent_channel"] == "MANUAL"


async def test_record_consent_rejects_invalid_phone(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    candidate = await _make_candidate(db_session)

    resp = await api_client.post(
        f"/candidates/{candidate.id}/consent", json={"phone_e164": "not-a-number"}
    )
    assert resp.status_code == 422


async def test_record_consent_unknown_candidate_422(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.post(
        f"/candidates/{uuid.uuid4()}/consent", json={"phone_e164": FAKE_NUMBER}
    )
    assert resp.status_code == 422
