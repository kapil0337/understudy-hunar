"""Launch and track outbound screening calls.

Two operations, both described in CONTRIBUTING.md:

  * call_candidates — the unbypassable consent/DNC guard, lazy agent_version publishing,
    preflight, and one POST /calls/ per allowed candidate.
  * refresh_outreach — polls Hunar for every non-terminal outreach row on a job not refreshed
    in the last 10 seconds, up to 10 at a time, concurrently. It runs on every board read and
    is what makes the board CORRECT: correctness never depends on a webhook arriving.
    app/services/webhooks.py (fed by POST /webhooks/hunar/{kind}) is what makes it feel FAST in
    between reads — both share the same status-precedence rule below, so a webhook and a poll
    can never disagree about whether a call is allowed to move backward.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.settings import Settings, get_settings
from app.integrations.hunar.client import HunarClient
from app.integrations.hunar.exceptions import HunarAdapterError, HunarAPIError
from app.integrations.hunar.models import (
    Agent,
    Call,
    CallbackConfig,
    CallCreate,
    CallRecordingWebhook,
    CallResultWebhook,
    CallStatusWebhook,
    CallSummaryWebhook,
    Guardrails,
    RetryConfig,
)
from app.integrations.hunar.preflight import check_custom_data, check_mobile_number
from app.models.agent_version import AgentVersion
from app.models.candidate import Candidate
from app.models.enums import CallStatus, Language
from app.models.job import Job
from app.models.outreach import Outreach
from app.schemas.compiled_jd import CompiledJD
from app.schemas.outreach import BlockedCandidate, CallLaunchSummary, QueuedCall
from app.services.jd_compiler import create_initial_version, publish_version
from app.services.rehearsal.score import EFFICIENCY_TARGET_SECONDS

logger = structlog.get_logger()


class OutreachError(Exception):
    """A batch-level failure — nothing candidate-specific to block, calling cannot proceed at
    all (e.g. the job has not been compiled yet)."""


# ------------------------------------------------------------------------------------- guard

#: Recruiter-visible block reasons for the unbypassable guard (CONTRIBUTING.md: "no override flag,
#: no env bypass"). Anything else in BlockedCandidate.reason is a preflight/API error message.
BLOCK_NOT_FOUND = "not_found"
BLOCK_DNC = "dnc"
BLOCK_NO_PHONE = "no_phone_number"
BLOCK_NO_CONSENT = "consent_not_recorded"


def check_call_allowed(candidate: Candidate, demo_allowed_numbers: set[str]) -> str | None:
    """None if the candidate may be called; otherwise the specific reason it was blocked.
    Checked in order dnc -> phone missing -> consent, so the most decisive reason wins when
    more than one applies."""
    if candidate.dnc:
        return BLOCK_DNC
    if candidate.phone_e164 is None:
        return BLOCK_NO_PHONE
    if candidate.phone_e164 not in demo_allowed_numbers and candidate.consent_recorded_at is None:
        return BLOCK_NO_CONSENT
    return None


def build_request_id(job_id: uuid.UUID, candidate_id: uuid.UUID, attempt: int) -> str:
    """f'{job_short}-{candidate_short}-a{attempt}' — the correlation key between our DB and
    Hunar (see app/models/outreach.py). Short hex slices keep it well under the 64-char limit."""
    return f"job{job_id.hex[:8]}-cand{candidate_id.hex[:8]}-a{attempt}"


async def _next_attempt_number(session: AsyncSession, candidate_id: uuid.UUID) -> int:
    count = (
        await session.execute(
            select(func.count())
            .select_from(Outreach)
            .where(col(Outreach.candidate_id) == candidate_id)
        )
    ).scalar_one()
    return int(count) + 1


# --------------------------------------------------------------------------- lazy publishing


async def _ensure_published_version(
    session: AsyncSession,
    job: Job,
    compiled: CompiledJD,
    language: Language,
    client: HunarClient,
) -> AgentVersion:
    """Reuse the latest AgentVersion for (job, language) if one exists, publishing it now if it
    has not been published yet; otherwise compile v1 fresh and publish that. Guarantees the
    returned version's hunar_agent_id is set."""
    existing = (
        (
            await session.execute(
                select(AgentVersion)
                .where(col(AgentVersion.job_id) == job.id, col(AgentVersion.language) == language)
                .order_by(col(AgentVersion.version_no).desc())
            )
        )
        .scalars()
        .first()
    )

    version = existing or await create_initial_version(session, job.id, compiled, language)
    if version.hunar_agent_id is None:
        version = await publish_version(session, version, client)
    assert version.hunar_agent_id is not None  # guaranteed by publish_version
    return version


_KNOWN_CUSTOM_VARIABLES = frozenset({"callee_name", "role_title", "role_location"})


def _build_custom_data(
    agent: Agent, candidate: Candidate, job: Job, compiled: CompiledJD
) -> dict[str, Any]:
    """custom_data must contain EVERY key in the agent's custom_variables (CONTRIBUTING.md). Only the
    three variables publish_version defaults to have a known value source; an agent declaring
    anything else fails loudly rather than sending an invented placeholder value."""
    unknown = [v for v in agent.custom_variables if v not in _KNOWN_CUSTOM_VARIABLES]
    if unknown:
        raise OutreachError(
            f"agent {agent.id} declares custom_variable(s) with no known value source: {unknown}"
        )
    location = compiled.locations[0] if compiled.locations else "the listed location"
    values = {
        "callee_name": candidate.full_name,
        "role_title": job.title,
        "role_location": location,
    }
    return {var: values[var] for var in agent.custom_variables}


# Fixed IST business-hours window: Hunar's guardrails are HH:MM with no documented timezone
# field on CallCreate (nothing in CONTRIBUTING.md's Hunar API facts names one), and every candidate
# in this project's scope is India-based, so a single fixed window is the honest choice rather
# than inventing an API field to carry a timezone that does not exist server-side.
DEFAULT_RETRY_CONFIG = RetryConfig(max_retry_count=2, retry_interval_hours=6)
DEFAULT_GUARDRAILS = Guardrails(
    allowed_days=["MON", "TUE", "WED", "THU", "FRI"],
    earliest_call_time="09:00",
    last_call_time="19:00",
)


def _callback_config(settings: Settings) -> CallbackConfig | None:
    """None when PUBLIC_BASE_URL is unset — calls still go out, just without a webhook URL
    Hunar could ever reach; refresh_outreach's polling covers correctness either way."""
    if not settings.public_base_url:
        return None
    base = settings.public_base_url.rstrip("/")
    return CallbackConfig(
        call_status_callback_url=f"{base}/webhooks/hunar/status",
        call_recording_callback_url=f"{base}/webhooks/hunar/recording",
        call_result_callback_url=f"{base}/webhooks/hunar/result",
        call_summary_callback_url=f"{base}/webhooks/hunar/summary",
    )


def _reason(exc: Exception) -> str:
    if isinstance(exc, HunarAPIError):
        return exc.operator_message
    return str(exc)


# ---------------------------------------------------------------------------- call_candidates


async def call_candidates(
    session: AsyncSession,
    job_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
    *,
    client: HunarClient,
    settings: Settings | None = None,
) -> CallLaunchSummary:
    settings = settings or get_settings()

    job = await session.get(Job, job_id)
    if job is None:
        raise OutreachError(f"no job with id {job_id}")
    if job.compiled is None:
        raise OutreachError(f"job {job_id} has not been compiled yet — nothing to call against")
    compiled = CompiledJD.model_validate(job.compiled)

    candidates = (
        (
            await session.execute(
                select(Candidate).where(
                    col(Candidate.job_id) == job_id, col(Candidate.id).in_(candidate_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {candidate.id: candidate for candidate in candidates}

    allowed_numbers = set(settings.demo_allowed_numbers_list)
    blocked: list[BlockedCandidate] = []
    by_language: dict[Language, list[Candidate]] = {}

    for candidate_id in candidate_ids:
        candidate = by_id.get(candidate_id)
        if candidate is None:
            blocked.append(BlockedCandidate(candidate_id=candidate_id, reason=BLOCK_NOT_FOUND))
            continue
        reason = check_call_allowed(candidate, allowed_numbers)
        if reason is not None:
            blocked.append(BlockedCandidate(candidate_id=candidate.id, reason=reason))
            continue
        language = candidate.preferred_language or Language.ENGLISH
        by_language.setdefault(language, []).append(candidate)

    versions_used: dict[str, uuid.UUID] = {}
    queued: list[QueuedCall] = []

    for language, group in by_language.items():
        try:
            version = await _ensure_published_version(session, job, compiled, language, client)
            assert version.hunar_agent_id is not None
            agent = await client.get_agent(version.hunar_agent_id)
        except HunarAdapterError as exc:
            reason = _reason(exc)
            for candidate in group:
                blocked.append(BlockedCandidate(candidate_id=candidate.id, reason=reason))
            continue

        versions_used[language.value] = version.id

        for candidate in group:
            try:
                custom_data = _build_custom_data(agent, candidate, job, compiled)
                check_custom_data(agent, custom_data)
                assert candidate.phone_e164 is not None  # guaranteed by check_call_allowed
                check_mobile_number(candidate.phone_e164)

                attempt = await _next_attempt_number(session, candidate.id)
                request_id = build_request_id(job.id, candidate.id, attempt)

                call = await client.create_call(
                    CallCreate(
                        agent_id=version.hunar_agent_id,
                        callee_name=candidate.full_name,
                        mobile_number=candidate.phone_e164,
                        custom_data=custom_data,
                        request_id=request_id,
                        retry_config=DEFAULT_RETRY_CONFIG,
                        guardrails=DEFAULT_GUARDRAILS,
                        callback_config=_callback_config(settings),
                    )
                )
            except (HunarAdapterError, OutreachError) as exc:
                blocked.append(BlockedCandidate(candidate_id=candidate.id, reason=_reason(exc)))
                continue

            try:
                status = CallStatus(call.status) if call.status else CallStatus.NOT_STARTED
            except ValueError:
                status = CallStatus.NOT_STARTED

            outreach = Outreach(
                candidate_id=candidate.id,
                agent_version_id=version.id,
                hunar_call_id=call.id,
                request_id=request_id,
                status=status,
                lifecycle_status="QUEUED",
            )
            session.add(outreach)
            await session.flush()
            queued.append(
                QueuedCall(
                    candidate_id=candidate.id,
                    outreach_id=outreach.id,
                    request_id=request_id,
                    hunar_call_id=call.id,
                )
            )

    await session.commit()
    logger.info(
        "call_candidates_launched", job_id=str(job_id), queued=len(queued), blocked=len(blocked)
    )

    return CallLaunchSummary(
        queued=queued,
        blocked=blocked,
        versions_used=versions_used,
        estimated_minutes=len(queued) * (EFFICIENCY_TARGET_SECONDS / 60.0),
    )


# ------------------------------------------------------------------------- status precedence

#: Monotonic ordering. Terminal statuses (>=5) are additionally sticky — see
#: apply_status_transition — so two different terminal statuses never overwrite each other
#: either, not just non-terminal ones regressing into an earlier terminal one.
_STATUS_PRECEDENCE: dict[CallStatus, int] = {
    CallStatus.NOT_STARTED: 0,
    CallStatus.SCHEDULED: 1,
    CallStatus.INITIATED: 2,
    CallStatus.RINGING: 3,
    CallStatus.IN_PROGRESS: 4,
    CallStatus.COMPLETED: 5,
    CallStatus.NOT_CONNECTED: 5,
    CallStatus.CANCELLED: 5,
    CallStatus.FAILED: 5,
}
TERMINAL_STATUSES = frozenset(
    {CallStatus.COMPLETED, CallStatus.NOT_CONNECTED, CallStatus.CANCELLED, CallStatus.FAILED}
)


def apply_status_transition(outreach: Outreach, new_status: CallStatus) -> bool:
    """Apply new_status if (and only if) it represents forward progress. Returns whether it was
    applied, so a caller can gate other field updates on the same event behind it — a status
    event that loses this check is stale in its entirety, not just its status field."""
    if outreach.status in TERMINAL_STATUSES:
        return False
    if _STATUS_PRECEDENCE[new_status] < _STATUS_PRECEDENCE[outreach.status]:
        return False
    outreach.status = new_status
    return True


def apply_status_webhook(outreach: Outreach, payload: CallStatusWebhook) -> bool:
    """Gated entirely behind apply_status_transition: if the status in this event cannot move
    the row forward, none of its accompanying detail is applied either, since a stale status
    implies stale detail."""
    if payload.status is None:
        return False
    if not apply_status_transition(outreach, CallStatus(payload.status)):
        return False
    if payload.lifecycle_status is not None:
        outreach.lifecycle_status = payload.lifecycle_status
    if payload.answered_by is not None:
        outreach.answered_by = payload.answered_by
    if payload.engagement_status is not None:
        outreach.engagement_status = payload.engagement_status
    if payload.duration_seconds is not None:
        outreach.duration_seconds = payload.duration_seconds
    if payload.error_message is not None:
        outreach.error_message = payload.error_message
    return True


def apply_recording_webhook(outreach: Outreach, payload: CallRecordingWebhook) -> None:
    if payload.recording_url is not None:
        outreach.recording_url = payload.recording_url
    if payload.duration_seconds is not None:
        outreach.duration_seconds = payload.duration_seconds


def apply_result_webhook(outreach: Outreach, payload: CallResultWebhook) -> None:
    if payload.result is not None:
        outreach.result = payload.result


def apply_summary_webhook(outreach: Outreach, payload: CallSummaryWebhook) -> None:
    if payload.summary is not None:
        outreach.call_summary = payload.summary


# ------------------------------------------------------------------------------ refresh_outreach

STALE_AFTER_SECONDS = 10
MAX_REFRESH_BATCH = 10
_NON_TERMINAL_STATUSES = tuple(status for status in CallStatus if status not in TERMINAL_STATUSES)


def _apply_call(outreach: Outreach, call: Call) -> None:
    if call.status is not None:
        try:
            apply_status_transition(outreach, CallStatus(call.status))
        except ValueError:
            logger.warning("refresh_outreach_unknown_status", status=call.status)
    if call.duration_seconds is not None:
        outreach.duration_seconds = call.duration_seconds
    if call.recording_url is not None:
        outreach.recording_url = call.recording_url
    if call.result is not None:
        outreach.result = call.result


async def refresh_outreach(
    session: AsyncSession, job_id: uuid.UUID, *, client: HunarClient
) -> list[Outreach]:
    """Poll Hunar for every non-terminal outreach row on this job not refreshed in the last 10
    seconds, up to 10 at a time, concurrently. Runs on every board read — this is what makes
    the board CORRECT regardless of whether a webhook ever arrives; see the module docstring.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=STALE_AFTER_SECONDS)
    rows = (
        (
            await session.execute(
                select(Outreach)
                .join(Candidate, col(Outreach.candidate_id) == col(Candidate.id))
                .where(
                    col(Candidate.job_id) == job_id,
                    col(Outreach.status).in_(_NON_TERMINAL_STATUSES),
                    col(Outreach.updated_at) < cutoff,
                )
                .order_by(col(Outreach.updated_at).asc())
                .limit(MAX_REFRESH_BATCH)
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return []

    async def _refresh_one(outreach: Outreach) -> Outreach:
        if outreach.hunar_call_id is not None:
            try:
                call = await client.get_call(outreach.hunar_call_id)
            except HunarAPIError as exc:
                logger.warning(
                    "refresh_outreach_poll_failed", outreach_id=str(outreach.id), error=str(exc)
                )
            else:
                _apply_call(outreach, call)
        # Touched unconditionally: a fetch failure or a genuinely unchanged status must still
        # advance the cursor, or this row is re-selected on every board read forever.
        outreach.updated_at = datetime.now(UTC)
        return outreach

    refreshed = list(await asyncio.gather(*(_refresh_one(row) for row in rows)))
    for outreach in refreshed:
        session.add(outreach)
    await session.commit()
    return refreshed
