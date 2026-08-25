from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import candidates, debug, jobs, patches, runs, versions, webhooks
from app.core.settings import get_settings
from app.schemas.guardrails import GuardrailsRead
from app.services import guardrails as guardrails_service

router = APIRouter()


@router.get("/healthz", tags=["health"], summary="Liveness and capability probe")
async def healthz() -> dict[str, object]:
    """Liveness/capability probe. Reports which optional integrations are configured
    so a reviewer running with only a database can see what's degraded and why."""
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
        "capabilities": settings.capabilities,
    }


@router.get(
    "/guardrails",
    tags=["jobs"],
    summary="The calling window and retry policy every published agent uses",
    description="One fixed, org-wide policy (app/services/guardrails.py) — sent explicitly on "
    "every publish rather than left to Hunar's org defaults, precisely so it can be read back "
    "here instead of being opaque.",
)
async def get_guardrails() -> GuardrailsRead:
    return GuardrailsRead(
        allowed_days=guardrails_service.GUARDRAILS.allowed_days,
        earliest_call_time=guardrails_service.GUARDRAILS.earliest_call_time,
        last_call_time=guardrails_service.GUARDRAILS.last_call_time,
        timezone=guardrails_service.TIMEZONE,
        max_retry_count=guardrails_service.RETRY_CONFIG.max_retry_count,
        retry_interval_hours=guardrails_service.RETRY_CONFIG.retry_interval_hours,
        inside_window_now=guardrails_service.is_within_calling_window(),
    )


router.include_router(jobs.router)
router.include_router(versions.router)
router.include_router(runs.router)
router.include_router(patches.router)
router.include_router(candidates.router)
router.include_router(webhooks.router)
router.include_router(debug.router)
