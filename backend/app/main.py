from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router as api_router
from app.core.errors import register_exception_handlers
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.settings import get_settings
from app.db.migrate import run_migrations_with_lock
from app.db.session import engine
from app.worker import poll_loop

settings = get_settings()
configure_logging(settings.log_level)

logger = structlog.get_logger()

#: Shown on /docs above each tag's routes — this is deliberately the first thing a reviewer
#: opening /docs sees, so it explains the shape of the product, not just the endpoints.
_OPENAPI_TAGS = [
    {
        "name": "jobs",
        "description": "A job holds the raw JD, its compiled requirements, agent versions, "
        "sourced candidates, and the live call board. Requirements are compiled into a new "
        "draft AgentVersion per language — versions are immutable, never edited in place.",
    },
    {
        "name": "rehearsal",
        "description": "Rehearse an agent version against six comparable personas before it "
        "ever calls a real person, score the result on four independent metrics, and patch the "
        "prompt to fix what failed — with the patch's effect measured by re-rehearsing, never "
        "assumed.",
    },
    {
        "name": "candidates",
        "description": "Per-candidate edits and consent. A call is only ever placed with an "
        "explicitly consented number (or one on the demo allow-list) — see POST "
        "/jobs/{id}/call's unbypassable guard.",
    },
    {
        "name": "webhooks",
        "description": "Inbound Hunar call-lifecycle events. Signature-verified, append-only "
        "logged regardless of outcome, and idempotent — GET /jobs/{id}/board's own polling is "
        "what keeps the board correct even if these never arrive.",
    },
    {
        "name": "debug",
        "description": "Diagnostic read-only views, not part of the product surface.",
    },
    {"name": "health", "description": "Liveness and capability probe."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await run_migrations_with_lock(engine)

    disabled = [name for name, enabled in settings.capabilities.items() if not enabled]
    if disabled:
        logger.warning("reduced_capability", disabled_integrations=disabled)
    else:
        logger.info("all_integrations_enabled")

    # See Settings.run_worker_inline: only set on a platform that can't run app/worker.py as
    # its own service at all. Everywhere else, the dedicated worker is strictly better (it
    # isn't tied to the API process's own restarts/sleep) and this task is never created.
    worker_task = asyncio.create_task(poll_loop()) if settings.run_worker_inline else None

    yield

    if worker_task is not None:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


app = FastAPI(
    title="Understudy",
    version="0.1.0",
    description="Rehearse-then-dial voice recruiting on the Hunar Voice Agents API.",
    lifespan=lifespan,
    openapi_tags=_OPENAPI_TAGS,
)

app.add_middleware(RequestIDMiddleware)
# The web app's own origin only — never "*", since credentials-free or not, this is the API
# surface a browser calls directly (CONTRIBUTING.md: no raw calls bypass the adapter/typed-client
# discipline on the frontend either).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)
register_exception_handlers(app)
app.include_router(api_router)
