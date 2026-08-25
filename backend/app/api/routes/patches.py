from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.runs import build_run_read
from app.db.session import get_db
from app.models.agent_version import AgentVersion
from app.models.job import Job
from app.models.rehearsal import PromptPatch, RehearsalRun
from app.schemas.compiled_jd import CompiledJD
from app.schemas.job import VersionSummary
from app.schemas.run import PatchAcceptResponse
from app.services.rehearsal.patch import PatchProposalError, accept_patch, score_delta

router = APIRouter(prefix="/patches", tags=["rehearsal"])


@router.post(
    "/{patch_id}/accept",
    summary="Accept a proposed patch",
    description="Creates AgentVersion n+1 (origin=PATCHED) from the patch's prompt, then "
    "immediately rehearses it against the same personas as the parent run — a patch's effect "
    "is measured, never assumed.",
)
async def accept_run_patch(
    patch_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> PatchAcceptResponse:
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
    compiled = CompiledJD.model_validate(job.compiled)

    try:
        accepted = await accept_patch(session, patch, compiled)
    except PatchProposalError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return PatchAcceptResponse(
        version=VersionSummary.model_validate(accepted.version, from_attributes=True),
        run=await build_run_read(session, accepted.run),
        score_delta=score_delta(base_run, accepted.run),
    )
