from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.router import router as api_router
from app.core.errors import register_exception_handlers
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.settings import get_settings
from app.db.migrate import run_migrations_with_lock
from app.db.session import engine

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
    yield


app = FastAPI(
    title="Understudy",
    version="0.1.0",
    description="Rehearse-then-dial voice recruiting on the Hunar Voice Agents API.",
    lifespan=lifespan,
    openapi_tags=_OPENAPI_TAGS,
)

app.add_middleware(RequestIDMiddleware)
register_exception_handlers(app)
app.include_router(api_router)
