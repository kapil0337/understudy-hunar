from __future__ import annotations

import uuid

import phonenumbers
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.integrations.hunar.preflight import PreflightError, check_mobile_number
from app.models.candidate import Candidate
from app.schemas.candidate import CandidatePatch, CandidateRead, ConsentCreate
from app.services.consent import ConsentError, record_consent

router = APIRouter(prefix="/candidates", tags=["candidates"])


async def _get_candidate(session: AsyncSession, candidate_id: uuid.UUID) -> Candidate:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no candidate with id {candidate_id}")
    return candidate


@router.patch(
    "/{candidate_id}",
    summary="Update a candidate's phone, language, or DNC flag",
    description="A plain field edit — unlike POST .../consent, this never sets "
    "consent_recorded_at. The outbound-call guard still checks consent independently at call "
    "time regardless of what phone_e164 is set to here.",
)
async def patch_candidate(
    candidate_id: uuid.UUID, body: CandidatePatch, session: AsyncSession = Depends(get_db)
) -> CandidateRead:
    candidate = await _get_candidate(session, candidate_id)

    if body.phone_e164 is not None:
        try:
            parsed = check_mobile_number(body.phone_e164)
        except PreflightError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        candidate.phone_e164 = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.E164
        )
    if body.preferred_language is not None:
        candidate.preferred_language = body.preferred_language
    if body.dnc is not None:
        candidate.dnc = body.dnc

    session.add(candidate)
    await session.commit()
    return CandidateRead.model_validate(candidate, from_attributes=True)


@router.post(
    "/{candidate_id}/consent",
    summary="Record consent",
    description="Sets phone_e164 and consent_recorded_at together — the only route that does, "
    "per CLAUDE.md's rule that a call needs an explicitly consented number.",
)
async def record_candidate_consent(
    candidate_id: uuid.UUID, body: ConsentCreate, session: AsyncSession = Depends(get_db)
) -> CandidateRead:
    try:
        candidate = await record_consent(
            session, candidate_id, body.phone_e164, channel=body.channel
        )
    except ConsentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return CandidateRead.model_validate(candidate, from_attributes=True)
