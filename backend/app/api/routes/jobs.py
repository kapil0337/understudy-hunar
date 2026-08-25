"""Everything nested under /jobs. Handlers stay thin: fetch, delegate to app/services/, shape
the response — no business logic lives here (CLAUDE.md)."""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.api.deps import get_hunar_client, get_optional_hunar_client
from app.db.session import get_db
from app.integrations.hunar.client import HunarClient
from app.integrations.hunar.exceptions import HunarAdapterError
from app.integrations.sourcing.base import SourcingQuery
from app.models.agent_version import AgentVersion
from app.models.candidate import Candidate
from app.models.enums import Language
from app.models.job import Job
from app.models.outreach import Outreach
from app.models.rehearsal import RehearsalRun
from app.schemas.board import BoardResponse, BoardRow
from app.schemas.candidate import CallRequest, CandidateRead, SourceRequest, SourceResponse
from app.schemas.compiled_jd import CompiledJD
from app.schemas.job import (
    JobCreate,
    JobRead,
    PersonaRead,
    RequirementsUpdate,
    RequirementsUpdateResponse,
    VersionHistoryRow,
    VersionSummary,
)
from app.schemas.outreach import CallLaunchSummary
from app.services.jd_compiler import compile_jd, create_initial_version, publish_version
from app.services.outreach import OutreachError, call_candidates, refresh_outreach
from app.services.personas import get_or_regenerate_personas
from app.services.ranking import apply_match, score_candidate
from app.services.sourcing import get_sourcing_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _get_job(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no job with id {job_id}")
    return job


def _require_compiled(job: Job) -> CompiledJD:
    if job.compiled is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"job {job.id} has not had requirements compiled yet — "
            "PUT /jobs/{id}/requirements first",
        )
    return CompiledJD.model_validate(job.compiled)


async def _latest_outreach(session: AsyncSession, candidate_id: uuid.UUID) -> Outreach | None:
    return (
        await session.execute(
            select(Outreach)
            .where(col(Outreach.candidate_id) == candidate_id)
            .order_by(col(Outreach.created_at).desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# ------------------------------------------------------------------------------------ jobs


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a job",
    description="Stores the raw job description. Nothing is compiled yet — "
    "PUT /jobs/{id}/requirements does that.",
)
async def create_job(body: JobCreate, session: AsyncSession = Depends(get_db)) -> JobRead:
    job = Job(title=body.title, raw_jd=body.raw_jd)
    session.add(job)
    await session.commit()
    return JobRead.model_validate(job, from_attributes=True)


@router.get("", summary="List jobs")
async def list_jobs(session: AsyncSession = Depends(get_db)) -> list[JobRead]:
    jobs = (await session.execute(select(Job).order_by(col(Job.created_at).desc()))).scalars().all()
    return [JobRead.model_validate(job, from_attributes=True) for job in jobs]


@router.get("/{job_id}", summary="Get one job")
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> JobRead:
    job = await _get_job(session, job_id)
    return JobRead.model_validate(job, from_attributes=True)


@router.put(
    "/{job_id}/requirements",
    summary="Update a job's requirements",
    description="Recompiles the raw JD and creates a new draft AgentVersion (origin=COMPILED, "
    "unpublished) for every language the compiled JD implies. Never edits an existing version — "
    "versions are immutable (CLAUDE.md).",
)
async def update_requirements(
    job_id: uuid.UUID, body: RequirementsUpdate, session: AsyncSession = Depends(get_db)
) -> RequirementsUpdateResponse:
    job = await _get_job(session, job_id)
    compiled = await compile_jd(body.raw_jd, session=session)

    job.raw_jd = body.raw_jd
    job.compiled = compiled.model_dump(mode="json")
    session.add(job)
    await session.flush()

    versions = [
        await create_initial_version(session, job.id, compiled, language)
        for language in compiled.candidate_languages
    ]
    await session.commit()

    return RequirementsUpdateResponse(
        job_id=job.id,
        versions=[VersionSummary.model_validate(v, from_attributes=True) for v in versions],
    )


@router.get(
    "/{job_id}/versions",
    summary="Version history with composite score per version",
)
async def list_versions(
    job_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> list[VersionHistoryRow]:
    await _get_job(session, job_id)
    versions = (
        (
            await session.execute(
                select(AgentVersion)
                .where(col(AgentVersion.job_id) == job_id)
                .order_by(col(AgentVersion.language), col(AgentVersion.version_no))
            )
        )
        .scalars()
        .all()
    )

    rows: list[VersionHistoryRow] = []
    for version in versions:
        latest_run = (
            await session.execute(
                select(RehearsalRun)
                .where(col(RehearsalRun.agent_version_id) == version.id)
                .order_by(col(RehearsalRun.started_at).desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        composite = (
            latest_run.scores.get("composite")
            if latest_run is not None and latest_run.scores is not None
            else None
        )
        rows.append(
            VersionHistoryRow(
                id=version.id,
                version_no=version.version_no,
                language=version.language,
                origin=version.origin,
                hunar_agent_id=version.hunar_agent_id,
                latest_composite_score=composite,
            )
        )
    return rows


@router.post(
    "/{job_id}/versions/{version_no}/publish",
    summary="Publish a draft version to Hunar",
    description="`language` disambiguates: versions are numbered per (job, language), so "
    "version_no alone is not unique across languages.",
)
async def publish_job_version(
    job_id: uuid.UUID,
    version_no: int,
    language: Language,
    session: AsyncSession = Depends(get_db),
    client: HunarClient = Depends(get_hunar_client),
) -> VersionSummary:
    await _get_job(session, job_id)
    version = (
        await session.execute(
            select(AgentVersion).where(
                col(AgentVersion.job_id) == job_id,
                col(AgentVersion.language) == language,
                col(AgentVersion.version_no) == version_no,
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no version {version_no} ({language.value}) for job {job_id}",
        )

    try:
        published = await publish_version(session, version, client)
    except HunarAdapterError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    await session.commit()
    return VersionSummary.model_validate(published, from_attributes=True)


@router.get("/{job_id}/personas", summary="The six rehearsal personas")
async def list_personas(
    job_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> list[PersonaRead]:
    job = await _get_job(session, job_id)
    compiled = _require_compiled(job)
    personas = await get_or_regenerate_personas(session, job.id, compiled)
    await session.commit()
    return [PersonaRead.model_validate(p, from_attributes=True) for p in personas]


# ------------------------------------------------------------------------------- candidates


@router.post(
    "/{job_id}/source",
    summary="Source candidates",
    description="Every field falls back to the job's own compiled search_query when omitted, "
    "so re-sourcing more of the same needs no body at all.",
)
async def source_candidates(
    job_id: uuid.UUID, body: SourceRequest, session: AsyncSession = Depends(get_db)
) -> SourceResponse:
    job = await _get_job(session, job_id)
    compiled = _require_compiled(job)

    query = SourcingQuery(
        titles=body.titles if body.titles is not None else compiled.search_query.titles,
        skills=body.skills if body.skills is not None else compiled.search_query.skills,
        locations=(
            body.locations if body.locations is not None else compiled.search_query.locations
        ),
        min_years=(
            body.min_years if body.min_years is not None else compiled.search_query.min_years
        ),
        limit=body.limit,
    )

    result = await get_sourcing_service().search(query, session=session)

    candidates: list[Candidate] = []
    for sourced in result.candidates:
        existing = (
            await session.execute(
                select(Candidate).where(
                    col(Candidate.job_id) == job_id,
                    col(Candidate.source_provider) == result.provider,
                    col(Candidate.source_ref) == sourced.source_ref,
                )
            )
        ).scalar_one_or_none()
        candidate = existing or Candidate(
            job_id=job_id,
            source_provider=result.provider,
            source_ref=sourced.source_ref,
            full_name=sourced.full_name,
            headline=sourced.headline,
            current_title=sourced.current_title,
            current_company=sourced.current_company,
            location=sourced.location,
            skills=sourced.skills,
            years_experience=sourced.years_experience,
            linkedin_url=sourced.linkedin_url,
            preferred_language=sourced.preferred_language,
            raw_payload=sourced.model_dump(mode="json"),
        )
        apply_match(candidate, score_candidate(candidate, compiled))
        session.add(candidate)
        await session.flush()
        candidates.append(candidate)

    await session.commit()
    return SourceResponse(
        provider=result.provider,
        cached=result.cached,
        candidates=[CandidateRead.model_validate(c, from_attributes=True) for c in candidates],
    )


@router.get(
    "/{job_id}/candidates",
    summary="List candidates, best match first",
)
async def list_candidates(
    job_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> list[CandidateRead]:
    await _get_job(session, job_id)
    candidates = (
        (
            await session.execute(
                select(Candidate)
                .where(col(Candidate.job_id) == job_id)
                .order_by(col(Candidate.match_score).desc().nulls_last())
            )
        )
        .scalars()
        .all()
    )
    return [CandidateRead.model_validate(c, from_attributes=True) for c in candidates]


@router.post(
    "/{job_id}/call",
    summary="Launch outbound screening calls",
    description="Blocked candidates are returned WITH reasons, never silently skipped — the "
    "consent/DNC guard is unbypassable (CLAUDE.md).",
)
async def launch_calls(
    job_id: uuid.UUID,
    body: CallRequest,
    session: AsyncSession = Depends(get_db),
    client: HunarClient = Depends(get_hunar_client),
) -> CallLaunchSummary:
    try:
        return await call_candidates(session, job_id, body.candidate_ids, client=client)
    except OutreachError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get(
    "/{job_id}/board",
    summary="The live candidate/call board",
    description="Refreshes non-terminal outreach rows on read (polling), then reads whatever "
    "state is current — the board is correct even if Hunar's webhooks never arrive.",
)
async def get_board(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    client: HunarClient | None = Depends(get_optional_hunar_client),
) -> BoardResponse:
    await _get_job(session, job_id)
    if client is not None:
        await refresh_outreach(session, job_id, client=client)

    candidates = (
        (
            await session.execute(
                select(Candidate)
                .where(col(Candidate.job_id) == job_id)
                .order_by(col(Candidate.match_score).desc().nulls_last())
            )
        )
        .scalars()
        .all()
    )

    # One query per candidate for their latest outreach — fine at the list sizes this board is
    # ever shown at (tens, not thousands); a join would trade readability for a scale this
    # project never reaches.
    rows = []
    for candidate in candidates:
        latest = await _latest_outreach(session, candidate.id)
        rows.append(
            BoardRow(
                candidate_id=candidate.id,
                full_name=candidate.full_name,
                match_score=candidate.match_score,
                phone_e164=candidate.phone_e164,
                consent_recorded_at=candidate.consent_recorded_at,
                dnc=candidate.dnc,
                outreach_id=latest.id if latest else None,
                status=latest.status.value if latest else None,
                lifecycle_status=latest.lifecycle_status if latest else None,
                duration_seconds=latest.duration_seconds if latest else None,
                recording_url=latest.recording_url if latest else None,
                result=latest.result if latest else None,
                call_summary=latest.call_summary if latest else None,
            )
        )
    return BoardResponse(job_id=job_id, rows=rows)


@router.get(
    "/{job_id}/export",
    summary="Export candidates as CSV",
    description="One row per candidate, one column per screening question id plus the four "
    "standard result fields, pulled from each candidate's latest call result.",
    response_class=Response,
)
async def export_candidates(job_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> Response:
    job = await _get_job(session, job_id)
    compiled = _require_compiled(job)

    candidates = (
        (
            await session.execute(
                select(Candidate)
                .where(col(Candidate.job_id) == job_id)
                .order_by(col(Candidate.match_score).desc().nulls_last())
            )
        )
        .scalars()
        .all()
    )

    question_ids = [q.id for q in compiled.screening_questions]
    standard_fields = ["interested", "qualified", "earliest_start", "rejection_reason"]
    fieldnames = [
        "candidate_id",
        "full_name",
        "phone_e164",
        "match_score",
        "consent_recorded_at",
        "dnc",
        "call_status",
        *question_ids,
        *standard_fields,
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    for candidate in candidates:
        latest = await _latest_outreach(session, candidate.id)
        result = (latest.result if latest else None) or {}
        row = {
            "candidate_id": str(candidate.id),
            "full_name": candidate.full_name,
            "phone_e164": candidate.phone_e164 or "",
            "match_score": candidate.match_score if candidate.match_score is not None else "",
            "consent_recorded_at": (
                candidate.consent_recorded_at.isoformat() if candidate.consent_recorded_at else ""
            ),
            "dnc": candidate.dnc,
            "call_status": latest.status.value if latest else "",
            **{field: result.get(field, "") for field in (*question_ids, *standard_fields)},
        }
        writer.writerow(row)

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="job-{job_id}-candidates.csv"'},
    )
