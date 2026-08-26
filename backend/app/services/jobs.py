"""Deleting a job. Not a Hunar API operation — purely local cleanup.

Every table that scopes data to a job (directly, or transitively via candidate/agent_version)
gets bulk-deleted in FK-safe order (children before parents) before the job row itself goes.
background_job and webhook_event rows are NOT FK'd to job_id (see their models — payload/
raw_payload only ever *mention* a job id inside JSON) so nothing here touches them: they're an
independent queue/log, not data scoped to this job.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.agent_version import AgentVersion
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.outreach import Outreach
from app.models.persona import Persona
from app.models.rehearsal import PromptPatch, RehearsalCase, RehearsalRun


async def delete_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    version_ids = select(col(AgentVersion.id)).where(col(AgentVersion.job_id) == job_id)
    run_ids = select(col(RehearsalRun.id)).where(
        col(RehearsalRun.agent_version_id).in_(version_ids)
    )
    candidate_ids = select(col(Candidate.id)).where(col(Candidate.job_id) == job_id)

    # Children first, so no FK ever points at a row that's already gone.
    await session.execute(delete(PromptPatch).where(col(PromptPatch.run_id).in_(run_ids)))
    await session.execute(delete(RehearsalCase).where(col(RehearsalCase.run_id).in_(run_ids)))
    await session.execute(
        delete(RehearsalRun).where(col(RehearsalRun.agent_version_id).in_(version_ids))
    )
    await session.execute(delete(Outreach).where(col(Outreach.candidate_id).in_(candidate_ids)))
    await session.execute(delete(Persona).where(col(Persona.job_id) == job_id))
    await session.execute(delete(AgentVersion).where(col(AgentVersion.job_id) == job_id))
    await session.execute(delete(Candidate).where(col(Candidate.job_id) == job_id))
    await session.execute(delete(Job).where(col(Job.id) == job_id))
