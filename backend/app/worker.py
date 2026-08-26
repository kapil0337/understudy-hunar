"""Claims BackgroundJob rows and runs the LLM-heavy operation each names.

poll_loop() is used two ways:

  * `python -m app.worker` — a second, portless process/service (see backend/Dockerfile,
    docker-compose.yml), so the API's HTTP request path never blocks on a multi-minute chain of
    LLM calls (see app/services/background_jobs.py for why this exists instead of running the
    work inline). This is the shape to prefer wherever the platform supports a second service.
  * app/main.py's lifespan, as a background asyncio task in the API process itself, when
    RUN_WORKER_INLINE=true — for a platform (e.g. a free-tier Render workspace) that doesn't
    support a second "background worker" service type at all. Same polling, same handlers, just
    sharing the API's own process instead of getting one of its own.

Deliberately simple: a sleep-poll loop, no signal handling beyond asyncio.CancelledError — an
in-flight job that gets killed by a deploy (or, inline, by the API process itself shutting down
mid-job) just leaves its BackgroundJob (and, for `rehearse`, its RehearsalRun) in RUNNING
forever, same as any other crash. Acceptable here; worth a retry/reaper pass before this carries
real traffic.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.migrate import run_migrations_with_lock
from app.db.session import async_session_factory, engine
from app.models.agent_version import AgentVersion
from app.models.job import Job
from app.models.rehearsal import RehearsalRun
from app.schemas.compiled_jd import CompiledJD
from app.services import background_jobs
from app.services.jd_compiler import compile_jd, create_initial_version
from app.services.personas import get_or_regenerate_personas
from app.services.rehearsal.patch import propose_patch
from app.services.rehearsal.run import rehearse_in_background

logger = structlog.get_logger()

POLL_INTERVAL_SECONDS = 2.0


async def _handle_compile_jd(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.UUID(payload["job_id"])
    raw_jd = payload["raw_jd"]

    job = await session.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")

    compiled = await compile_jd(raw_jd, session=session)

    job.raw_jd = raw_jd
    job.compiled = compiled.model_dump(mode="json")
    session.add(job)
    await session.flush()

    versions = [
        await create_initial_version(session, job.id, compiled, language)
        for language in compiled.candidate_languages
    ]
    await session.commit()
    return {"job_id": str(job.id), "version_ids": [str(v.id) for v in versions]}


async def _handle_regenerate_personas(
    session: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    job_id = uuid.UUID(payload["job_id"])

    job = await session.get(Job, job_id)
    if job is None or job.compiled is None:
        raise ValueError(f"job {job_id} has no compiled JD")

    compiled = CompiledJD.model_validate(job.compiled)
    personas = await get_or_regenerate_personas(session, job.id, compiled)
    await session.commit()
    return {"persona_ids": [str(p.id) for p in personas]}


async def _handle_propose_patch(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = uuid.UUID(payload["run_id"])

    run = await session.get(RehearsalRun, run_id)
    if run is None:
        raise ValueError(f"rehearsal_run {run_id} not found")
    version = await session.get(AgentVersion, run.agent_version_id)
    if version is None:
        raise ValueError(f"agent_version {run.agent_version_id} not found")
    job = await session.get(Job, version.job_id)
    if job is None or job.compiled is None:
        raise ValueError(f"job {version.job_id} has no compiled JD")

    compiled = CompiledJD.model_validate(job.compiled)
    patch = await propose_patch(session, run, compiled)
    await session.commit()
    return {"patch_id": str(patch.id)}


async def _handle_rehearse(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    # rehearse_in_background opens and commits its own session (it's also the entry point a
    # future retry/reaper pass would call directly) — nothing left to do with `session` here.
    agent_version_id = uuid.UUID(payload["agent_version_id"])
    run_id = uuid.UUID(payload["run_id"])
    await rehearse_in_background(agent_version_id, run_id)
    return {"run_id": str(run_id)}


_HANDLERS: dict[str, Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "compile_jd": _handle_compile_jd,
    "regenerate_personas": _handle_regenerate_personas,
    "propose_patch": _handle_propose_patch,
    "rehearse": _handle_rehearse,
}


async def _process_one() -> bool:
    """Claim and run one job. Returns False if the queue was empty (caller should sleep)."""
    async with async_session_factory() as session:
        job = await background_jobs.claim_next(session)
        if job is None:
            return False

        handler = _HANDLERS.get(job.kind)
        try:
            if handler is None:
                raise ValueError(f"unknown background_job kind {job.kind!r}")
            result = await handler(session, job.payload)
        except Exception as exc:  # noqa: BLE001 - deliberately broad: any handler failure
            # becomes a FAILED job row rather than crashing the worker loop.
            logger.exception("background_job_failed", job_id=str(job.id), kind=job.kind)
            await session.rollback()  # discard any partial writes the handler made
            await background_jobs.mark_failed(session, job, str(exc))
        else:
            await background_jobs.mark_completed(session, job, result)

        return True


async def poll_loop() -> None:
    """Runs until cancelled. Caller is responsible for migrations having already run — main()
    below does that for the standalone process; app/main.py's lifespan already does it for the
    API itself before ever spawning this as a background task."""
    logger.info("worker_started")
    while True:
        processed = await _process_one()
        if not processed:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await run_migrations_with_lock(engine)
    await poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
