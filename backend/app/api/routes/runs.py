from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.db.session import get_db
from app.models.agent_version import AgentVersion
from app.models.job import Job
from app.models.persona import Persona
from app.models.rehearsal import RehearsalCase, RehearsalRun
from app.schemas.compiled_jd import CompiledJD
from app.schemas.run import CaseRead, CaseSummary, PatchRead, RunRead
from app.services.rehearsal.patch import PatchProposalError, propose_patch

router = APIRouter(tags=["rehearsal"])


async def _get_run(session: AsyncSession, run_id: uuid.UUID) -> RehearsalRun:
    run = await session.get(RehearsalRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no rehearsal_run with id {run_id}")
    return run


async def _compiled_for_run(session: AsyncSession, run: RehearsalRun) -> CompiledJD:
    version = await session.get(AgentVersion, run.agent_version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no agent_version for run {run.id}")
    job = await session.get(Job, version.job_id)
    if job is None or job.compiled is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"job {version.job_id} has no compiled JD")
    return CompiledJD.model_validate(job.compiled)


async def build_run_read(session: AsyncSession, run: RehearsalRun) -> RunRead:
    """Shared by GET /runs/{id} and POST /patches/{id}/accept's response, so a freshly-accepted
    patch's resulting run comes back with the same case_summaries a direct GET would show."""
    cases = (
        (await session.execute(select(RehearsalCase).where(col(RehearsalCase.run_id) == run.id)))
        .scalars()
        .all()
    )
    personas_by_id = {
        persona.id: persona
        for persona in (
            await session.execute(
                select(Persona).where(col(Persona.id).in_([case.persona_id for case in cases]))
            )
        )
        .scalars()
        .all()
    }

    return RunRead(
        id=run.id,
        agent_version_id=run.agent_version_id,
        status=run.status,
        scores=run.scores,
        llm_calls=run.llm_calls,
        cached_calls=run.cached_calls,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        case_summaries=[
            CaseSummary(
                id=case.id,
                persona_id=case.persona_id,
                archetype=personas_by_id[case.persona_id].archetype,
                turn_count=case.turn_count,
                estimated_seconds=case.estimated_seconds,
            )
            for case in cases
            if case.persona_id in personas_by_id
        ],
    )


@router.get(
    "/runs/{run_id}",
    summary="A rehearsal run's status, scores, and per-case summaries",
)
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> RunRead:
    run = await _get_run(session, run_id)
    return await build_run_read(session, run)


@router.get(
    "/runs/{run_id}/cases/{case_id}",
    summary="One persona's full transcript, extraction, ground truth, metrics and failures",
)
async def get_case(
    run_id: uuid.UUID, case_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> CaseRead:
    await _get_run(session, run_id)
    case = await session.get(RehearsalCase, case_id)
    if case is None or case.run_id != run_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no case {case_id} on run {run_id}")
    persona = await session.get(Persona, case.persona_id)
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no persona for case {case_id}")

    return CaseRead(
        id=case.id,
        run_id=case.run_id,
        persona_id=case.persona_id,
        archetype=persona.archetype,
        transcript=case.transcript,
        extracted_result=case.extracted_result,
        ground_truth=persona.ground_truth,
        metrics=case.metrics,
        failures=case.failures,
    )


@router.post(
    "/runs/{run_id}/patch",
    summary="Propose a prompt patch addressing this run's worst failures",
)
async def propose_run_patch(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> PatchRead:
    run = await _get_run(session, run_id)
    compiled = await _compiled_for_run(session, run)

    try:
        patch = await propose_patch(session, run, compiled)
    except PatchProposalError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()

    return PatchRead(
        id=patch.id,
        run_id=patch.run_id,
        proposed_agent_prompt=patch.proposed_agent_prompt,
        rationale=patch.rationale,
        accepted=patch.accepted,
        resulting_version_id=patch.resulting_version_id,
    )
