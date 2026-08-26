from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.agent_version import AgentVersion
from app.models.job import Job
from app.models.rehearsal import PromptPatch, RehearsalRun
from app.schemas.job import VersionSummary
from app.schemas.run import PatchAcceptAccepted, PatchRead
from app.services.rehearsal.patch import PatchProposalError, create_accepted_patch_version
from app.services.rehearsal.run import create_and_enqueue_rehearsal

router = APIRouter(prefix="/patches", tags=["rehearsal"])


@router.get(
    "/{patch_id}",
    summary="One proposed patch",
    description="Fetch a patch proposed by POST /runs/{id}/patch — that endpoint returns 202 "
    "immediately since proposing a patch is an LLM call; poll GET /background-jobs/{id} then "
    "fetch it here once COMPLETED.",
)
async def get_patch(patch_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> PatchRead:
    patch = await session.get(PromptPatch, patch_id)
    if patch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no prompt_patch with id {patch_id}")
    return PatchRead(
        id=patch.id,
        run_id=patch.run_id,
        proposed_agent_prompt=patch.proposed_agent_prompt,
        rationale=patch.rationale,
        accepted=patch.accepted,
        resulting_version_id=patch.resulting_version_id,
    )


@router.post(
    "/{patch_id}/accept",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a proposed patch",
    description="Creates AgentVersion n+1 (origin=PATCHED) from the patch's prompt immediately, "
    "then enqueues rehearsing it against the same personas as the parent run — a patch's effect "
    "is measured, never assumed. Poll GET /versions/{version.id}/latest-run for the rehearsal.",
)
async def accept_run_patch(
    patch_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> PatchAcceptAccepted:
    patch = await session.get(PromptPatch, patch_id)
    if patch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no prompt_patch with id {patch_id}")

    base_run = await session.get(RehearsalRun, patch.run_id)
    if base_run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no rehearsal_run for patch {patch_id}")
    base_version = await session.get(AgentVersion, base_run.agent_version_id)
    if base_version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no agent_version for patch's run")
    job = await session.get(Job, base_version.job_id)
    if job is None or job.compiled is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"job {base_version.job_id} has no compiled JD"
        )

    try:
        new_version = await create_accepted_patch_version(session, patch)
    except PatchProposalError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    run = await create_and_enqueue_rehearsal(session, new_version)

    return PatchAcceptAccepted(
        version=VersionSummary.model_validate(new_version, from_attributes=True),
        run_id=run.id,
        status=run.status,
    )
