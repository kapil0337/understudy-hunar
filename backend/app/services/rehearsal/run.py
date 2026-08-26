"""Run a full rehearsal: simulate every persona, score the run, and persist the result.

Ties simulate.py (the two-actor call simulation) and score.py (the four-metric scorer) into the
one operation everything else in this package needs — propose_patch and accept_patch both score
a run's failures or start a fresh one, and scripts/demo_rehearsal.py just calls this twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_version import AgentVersion
from app.models.persona import Persona
from app.models.rehearsal import RehearsalCase, RehearsalRun
from app.schemas.compiled_jd import CompiledJD
from app.schemas.rehearsal import CaseInput, RehearsalScore, TranscriptTurn
from app.services.llm import LLMService, get_llm_service
from app.services.rehearsal.score import score_rehearsal_run
from app.services.rehearsal.simulate import run_rehearsal_cases

logger = structlog.get_logger()


def _case_input(case: RehearsalCase, persona: Persona) -> CaseInput:
    return CaseInput(
        persona_id=persona.id,
        archetype=persona.archetype,
        ground_truth=persona.ground_truth,
        off_script_questions=persona.behaviour.get("off_script_questions", []),
        transcript=[TranscriptTurn.model_validate(turn) for turn in (case.transcript or [])],
        extracted_result=case.extracted_result or {},
        estimated_seconds=case.estimated_seconds or 0.0,
        turn_count=case.turn_count or 0,
    )


def _apply_case_scores(cases: list[RehearsalCase], score: RehearsalScore) -> None:
    """Split the run-wide RehearsalScore back out per persona onto each RehearsalCase row, so a
    case's own row carries exactly what its own persona scored and failed on."""
    extraction_by_persona: dict[uuid.UUID, list[Any]] = {}
    for field in score.extraction_accuracy.fields:
        extraction_by_persona.setdefault(field.persona_id, []).append(field.model_dump(mode="json"))

    efficiency_by_persona = {
        c.persona_id: c.model_dump(mode="json") for c in score.efficiency.cases
    }
    coverage_by_persona = {c.persona_id: c.model_dump(mode="json") for c in score.coverage.cases}
    faithfulness_by_persona = {
        c.persona_id: c.model_dump(mode="json") for c in score.faithfulness.cases
    }

    failures_by_persona: dict[uuid.UUID, list[Any]] = {}
    for failure in score.failures:
        failures_by_persona.setdefault(failure.persona_id, []).append(
            failure.model_dump(mode="json")
        )

    for case in cases:
        case.metrics = {
            "extraction_accuracy": {"fields": extraction_by_persona.get(case.persona_id, [])},
            "efficiency": efficiency_by_persona.get(case.persona_id),
            "coverage": coverage_by_persona.get(case.persona_id),
            "faithfulness": faithfulness_by_persona.get(case.persona_id),
        }
        case.failures = failures_by_persona.get(case.persona_id, [])


async def run_rehearsal(
    session: AsyncSession,
    agent_version: AgentVersion,
    compiled: CompiledJD,
    personas: list[Persona],
    *,
    llm: LLMService | None = None,
    concurrency: int = 3,
    run: RehearsalRun | None = None,
) -> RehearsalRun:
    """Simulate every persona against agent_version, score the run, and persist all of it: the
    RehearsalRun row, one RehearsalCase per successfully-simulated persona (each carrying its
    own metrics/failures), and the run's aggregate scores + status.

    `run` lets a caller reuse an already-created, already-committed row (e.g. the API's
    POST /versions/{id}/rehearse, which creates a PENDING row and returns its id in the 202
    response before a background task calls this) instead of creating a fresh one — the id the
    caller already handed back stays the id this fills in. Most callers omit it and get a new
    row, unchanged from before.

    Commits internally (both on success and on total failure) rather than just flushing, unlike
    most of this codebase's service functions — by the time this returns, the run's fate is
    durably recorded, which is what lets callers (accept_patch, the demo script) treat the
    returned RehearsalRun as final rather than re-committing it themselves.
    """
    service = llm or get_llm_service()
    calls_before, cached_before = service.stats.calls, service.stats.cached

    if run is None:
        run = RehearsalRun(agent_version_id=agent_version.id, status="RUNNING")
    else:
        run.status = "RUNNING"
    session.add(run)
    await session.flush()

    cases = await run_rehearsal_cases(
        session, run.id, agent_version, compiled, personas, llm=service, concurrency=concurrency
    )

    if not cases:
        run.status = "FAILED"
        run.error = "every persona simulation failed — see logs for individual errors"
        run.finished_at = datetime.now(UTC)
        run.llm_calls = service.stats.calls - calls_before
        run.cached_calls = service.stats.cached - cached_before
        session.add(run)
        await session.commit()
        logger.error("rehearsal_run_failed", run_id=str(run.id))
        return run

    by_persona_id = {persona.id: persona for persona in personas}
    case_inputs = [_case_input(case, by_persona_id[case.persona_id]) for case in cases]

    score = await score_rehearsal_run(compiled, case_inputs, llm=service)
    _apply_case_scores(cases, score)
    for case in cases:
        session.add(case)

    run.scores = score.model_dump(mode="json")
    run.status = "COMPLETED"
    run.finished_at = datetime.now(UTC)
    run.llm_calls = service.stats.calls - calls_before
    run.cached_calls = service.stats.cached - cached_before
    session.add(run)
    await session.commit()

    logger.info("rehearsal_run_completed", run_id=str(run.id), composite=score.composite)
    return run


async def rehearse_in_background(agent_version_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """Entry point for app/worker.py's "rehearse" job kind: the route (POST
    /versions/{id}/rehearse or POST /patches/{id}/accept) creates a PENDING RehearsalRun and
    enqueues a BackgroundJob before this ever runs, so this function opens its own session
    rather than reusing the (by-then-closed) request session.
    """
    from app.db.session import async_session_factory
    from app.models.job import Job
    from app.services.personas import get_or_regenerate_personas

    async with async_session_factory() as session:
        version = await session.get(AgentVersion, agent_version_id)
        run = await session.get(RehearsalRun, run_id)
        if version is None or run is None:
            logger.error(
                "rehearse_in_background_missing_row",
                agent_version_id=str(agent_version_id),
                run_id=str(run_id),
            )
            return

        job = await session.get(Job, version.job_id)
        if job is None or job.compiled is None:
            run.status = "FAILED"
            run.error = f"job {version.job_id} has no compiled JD"
            run.finished_at = datetime.now(UTC)
            session.add(run)
            await session.commit()
            return

        compiled = CompiledJD.model_validate(job.compiled)
        personas = await get_or_regenerate_personas(session, job.id, compiled)
        await session.commit()

        await run_rehearsal(session, version, compiled, personas, run=run)


async def create_and_enqueue_rehearsal(
    session: AsyncSession, version: AgentVersion
) -> RehearsalRun:
    """Create a PENDING RehearsalRun and enqueue the worker job that will run it — shared by
    POST /versions/{id}/rehearse and POST /patches/{id}/accept, both of which defer the same
    work rather than running run_rehearsal inline in the request."""
    from app.services import background_jobs

    run = RehearsalRun(agent_version_id=version.id, status="PENDING")
    session.add(run)
    await session.flush()
    await background_jobs.enqueue(
        session,
        "rehearse",
        {"agent_version_id": str(version.id), "run_id": str(run.id)},
    )
    await session.commit()
    return run
