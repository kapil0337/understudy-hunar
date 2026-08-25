from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import candidates, debug, jobs, patches, runs, versions, webhooks
from app.core.settings import get_settings

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


router.include_router(jobs.router)
router.include_router(versions.router)
router.include_router(runs.router)
router.include_router(patches.router)
router.include_router(candidates.router)
router.include_router(webhooks.router)
router.include_router(debug.router)
