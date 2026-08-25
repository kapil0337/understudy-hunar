from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.api.routes.runs import build_run_read
from app.db.session import get_db
from app.models.agent_version import AgentVersion
from app.models.job import Job
from app.models.rehearsal import RehearsalRun
from app.schemas.job import AgentVersionRead
from app.schemas.run import RehearseAccepted, RunRead
from app.services.rehearsal.run import rehearse_in_background

router = APIRouter(prefix="/versions", tags=["rehearsal"])


@router.get(
    "/{version_id}",
    summary="One agent version's full built prompt and result schema",
)
async def get_version(
    version_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> AgentVersionRead:
    version = await session.get(AgentVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no agent_version with id {version_id}")
    return AgentVersionRead.model_validate(version, from_attributes=True)


@router.post(
    "/{version_id}/rehearse",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Rehearse an agent version",
    description="Runs all six personas against this version and scores the result. Returns "
    "immediately with a run id in PENDING status; poll GET /runs/{id} for progress.",
)
async def rehearse_version(
    version_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> RehearseAccepted:
    version = await session.get(AgentVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no agent_version with id {version_id}")

    job = await session.get(Job, version.job_id)
    if job is None or job.compiled is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"job {version.job_id} has no compiled JD to rehearse against"
        )

    run = RehearsalRun(agent_version_id=version.id, status="PENDING")
    session.add(run)
    await session.commit()

    background_tasks.add_task(rehearse_in_background, version.id, run.id)
    return RehearseAccepted(run_id=run.id, status=run.status)


@router.get(
    "/{version_id}/latest-run",
    summary="This version's most recent rehearsal run, if it has one",
    description="null if the version has never been rehearsed — a valid state, not an error, "
    "so this returns 200 rather than 404.",
)
async def get_latest_run(
    version_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> RunRead | None:
    run = (
        await session.execute(
            select(RehearsalRun)
            .where(col(RehearsalRun.agent_version_id) == version_id)
            .order_by(col(RehearsalRun.started_at).desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    return await build_run_read(session, run)
