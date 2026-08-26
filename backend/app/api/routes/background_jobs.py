from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.background_job import BackgroundJob
from app.schemas.background_job import BackgroundJobRead

router = APIRouter(prefix="/background-jobs", tags=["jobs"])


@router.get(
    "/{background_job_id}",
    summary="Status of a deferred LLM-heavy operation",
    description="The one poll target shared by every operation the API defers to app/worker.py "
    "(compile_jd, regenerate_personas, propose_patch, rehearse) — PENDING/RUNNING/COMPLETED/"
    "FAILED, same convention as RehearsalRun.status.",
)
async def get_background_job(
    background_job_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> BackgroundJobRead:
    job = await session.get(BackgroundJob, background_job_id)
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no background_job with id {background_job_id}"
        )
    return BackgroundJobRead.model_validate(job, from_attributes=True)
