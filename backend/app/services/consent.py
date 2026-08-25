"""Consent recording and the pluggable outbound channel that requests it.

ConsentChannel is a Protocol so a real channel (WhatsApp) can drop in later without touching
record_consent or anything that reads Candidate.consent_recorded_at/phone_e164/dnc.
ManualConsentChannel is the only implementation today: the recruiter enters a number and ticks a
consent box in the UI, which calls record_consent() directly. There is no outbound message to
send and no inbound webhook to receive for that flow, so both Protocol methods on it are stubs
that point back at record_consent() — they exist to satisfy the Protocol uniformly, not because
manual consent has a round trip.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, Protocol, runtime_checkable

import phonenumbers
import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, get_settings
from app.integrations.hunar.preflight import PreflightError, check_mobile_number
from app.models._shared import utcnow
from app.models.candidate import Candidate
from app.models.job import Job

logger = structlog.get_logger()


class ConsentError(Exception):
    """Base error for consent recording failures."""


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: uuid.UUID
    channel: str
    status: Literal["sent", "not_applicable"]
    detail: str


class ConsentOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: uuid.UUID
    outcome: Literal["consented", "declined", "pending"]
    channel: str
    phone_e164: str | None = None


@runtime_checkable
class ConsentChannel(Protocol):
    name: str

    async def request_consent(self, candidate: Candidate, job: Job) -> ConsentRequest: ...

    async def handle_inbound(self, payload: dict[str, Any]) -> ConsentOutcome: ...


class ManualConsentChannel:
    name = "MANUAL"

    async def request_consent(self, candidate: Candidate, job: Job) -> ConsentRequest:
        return ConsentRequest(
            candidate_id=candidate.id,
            channel=self.name,
            status="not_applicable",
            detail=(
                "Manual channel has no outbound step. The recruiter enters a number and ticks "
                "a consent box in the UI, which calls record_consent() directly."
            ),
        )

    async def handle_inbound(self, payload: dict[str, Any]) -> ConsentOutcome:
        raise NotImplementedError(
            "ManualConsentChannel has no inbound flow; call record_consent() directly."
        )


def build_consent_channel(settings: Settings | None = None) -> ConsentChannel:
    """CHANNEL env var picks the implementation. WhatsApp is a documented seam only: every call
    into it raises NotImplementedError until it is built — see app/integrations/whatsapp."""
    settings = settings or get_settings()
    if settings.channel == "whatsapp":
        from app.integrations.whatsapp.channel import WhatsAppConsentChannel

        return WhatsAppConsentChannel()
    return ManualConsentChannel()


def _to_e164(phone: str) -> str:
    try:
        parsed = check_mobile_number(phone)
    except PreflightError as exc:
        raise ConsentError(str(exc)) from exc
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


async def record_consent(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    phone_e164: str,
    *,
    channel: str = "MANUAL",
) -> Candidate:
    """Set phone_e164 and consent_recorded_at on a candidate. This is the ONLY place those two
    fields are written together — the hard rule in CLAUDE.md (no outbound call without consent)
    depends on nothing else being able to set them independently of each other."""
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise ConsentError(f"No candidate with id {candidate_id}")

    candidate.phone_e164 = _to_e164(phone_e164)
    candidate.consent_recorded_at = utcnow()
    candidate.consent_channel = channel
    session.add(candidate)
    await session.flush()
    logger.info("consent_recorded", candidate_id=str(candidate_id), channel=channel)
    return candidate


async def record_decline(
    session: AsyncSession, candidate_id: uuid.UUID, *, channel: str = "MANUAL"
) -> Candidate:
    """Set dnc=True. Used by real channels' negative-reply handling — see
    app/integrations/whatsapp/channel.py's module docstring."""
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise ConsentError(f"No candidate with id {candidate_id}")

    candidate.dnc = True
    session.add(candidate)
    await session.flush()
    logger.info("consent_declined", candidate_id=str(candidate_id), channel=channel)
    return candidate
