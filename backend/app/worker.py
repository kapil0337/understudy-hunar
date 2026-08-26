"""Worker process: continuously polls for BackgroundJob rows and runs them via
app/services/job_runner.py.

Run with `python -m app.worker`. Same image/deps as the API (see backend/Dockerfile) — deployed
as a second, portless service so the API's HTTP request path never blocks on a multi-minute
chain of LLM calls (see app/services/background_jobs.py for why this exists instead of running
the work inline).

Only for a deployment with a persistent process to run this loop in (Docker/Render — see
render.yaml). A serverless deployment (Vercel) has no such process at all; it uses
app/api/routes/internal.py instead, invoked by Cron and by a best-effort nudge right after
enqueueing (background_jobs.enqueue_and_trigger) — see that route's docstring for why.

Deliberately simple: one process, a sleep-poll loop, no signal handling — an in-flight job that
gets killed by a deploy just leaves its BackgroundJob (and, for `rehearse`, its RehearsalRun) in
RUNNING forever, same as any other crash. Acceptable here; worth a retry/reaper pass before this
carries real traffic.
"""

from __future__ import annotations

import asyncio

import structlog

from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.migrate import run_migrations_with_lock
from app.db.session import engine
from app.services.job_runner import process_one

logger = structlog.get_logger()

POLL_INTERVAL_SECONDS = 2.0


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await run_migrations_with_lock(engine)
    logger.info("worker_started")

    while True:
        processed = await process_one()
        if not processed:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
