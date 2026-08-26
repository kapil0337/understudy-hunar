"""Postgres-backed job queue: enqueue from a route, claim-and-execute from app/worker.py.

Exists because compile_jd, regenerate_personas, propose_patch, and rehearse each make several
sequential LLM calls and can run for minutes — too long to run inline in a request handler that
might be served by a short-timeout serverless function (see docs/architecture or the plan this
implements). No new infra: the background_job table IS the queue, claimed with
`FOR UPDATE SKIP LOCKED` so multiple worker instances never double-process the same row — the
same pattern the rest of this app already uses Postgres for instead of an external queue
(RehearsalRun.status, refresh_outreach's polling).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.background_job import BackgroundJob

JobKind = Literal["compile_jd", "regenerate_personas", "propose_patch", "rehearse"]


async def enqueue(session: AsyncSession, kind: JobKind, payload: dict[str, Any]) -> BackgroundJob:
    job = BackgroundJob(kind=kind, payload=payload)
    session.add(job)
    await session.flush()
    return job


async def claim_next(session: AsyncSession) -> BackgroundJob | None:
    """Atomically claim the oldest PENDING job and mark it RUNNING, or None if none is waiting.

    Commits immediately so the RUNNING status and the row lock's release are visible to other
    worker instances right away, rather than staying held for however long the job itself takes.
    """
    job = (
        await session.execute(
            select(BackgroundJob)
            .where(col(BackgroundJob.status) == "PENDING")
            .order_by(col(BackgroundJob.created_at))
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if job is None:
        return None

    job.status = "RUNNING"
    job.started_at = datetime.now(UTC)
    session.add(job)
    await session.commit()
    return job


async def mark_completed(session: AsyncSession, job: BackgroundJob, result: dict[str, Any]) -> None:
    job.status = "COMPLETED"
    job.result = result
    job.finished_at = datetime.now(UTC)
    session.add(job)
    await session.commit()


async def mark_failed(session: AsyncSession, job: BackgroundJob, error: str) -> None:
    job.status = "FAILED"
    job.error = error
    job.finished_at = datetime.now(UTC)
    session.add(job)
    await session.commit()
