"""Serverless-friendly replacement for app/worker.py's continuous poll loop — only relevant to
a deployment with no persistent process to run that loop in (Vercel; see backend/vercel.json).
Docker and Render keep using app/worker.py and never call this at all.

Two callers, both must present CRON_SECRET since this drains real LLM-call budget:

  * Vercel Cron, on whatever schedule the plan allows — the guaranteed-eventually path.
  * background_jobs.enqueue_and_trigger's best-effort nudge, fired right after enqueueing, so a
    serverless deployment feels as responsive as the polling worker instead of waiting for the
    next Cron tick.

GET, not POST, despite having a side effect: Vercel Cron invokes the configured path with GET,
and matching that (rather than adding a second route) keeps both callers hitting the exact same
handler.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.core.settings import get_settings
from app.services.job_runner import drain

router = APIRouter(prefix="/internal", tags=["internal"])

#: One job per invocation, not a larger batch: an individual job can itself run for minutes
#: (see app/services/background_jobs.py), so even one already risks a serverless function's
#: execution-time limit — stacking several sequentially in one invocation only compounds that.
#: Multiple pending jobs still drain promptly regardless, since each enqueue fires its own
#: trigger (app/services/background_jobs.py's enqueue_and_trigger) and concurrent invocations
#: claim distinct rows safely (FOR UPDATE SKIP LOCKED). A single job that outlives the
#: function's own timeout hits the same known limitation app/worker.py already documents for a
#: mid-job deploy kill — not a new failure mode, just a new way to trigger it.
_MAX_JOBS_PER_DRAIN = 1


@router.get(
    "/process-jobs",
    summary="Claim and run a bounded batch of pending background jobs",
    description="Not part of the product API — see this module's docstring. 404s when "
    "CRON_SECRET isn't configured, so a deployment that doesn't need this (Docker/Render, "
    "where app/worker.py already polls) never exposes it at all.",
)
async def process_jobs(authorization: Annotated[str | None, Header()] = None) -> dict[str, int]:
    settings = get_settings()
    if not settings.cron_secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    expected = f"Bearer {settings.cron_secret}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    processed = await drain(_MAX_JOBS_PER_DRAIN)
    return {"processed": processed}
