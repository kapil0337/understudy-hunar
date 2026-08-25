from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.db.session import get_db
from app.models.webhook_event import WebhookEvent
from app.schemas.debug import WebhookEventRead

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get(
    "/webhooks",
    summary="Recent raw webhook events, valid or not",
    description="The append-only log every inbound Hunar webhook is recorded to, regardless of "
    "whether its signature verified or it resolved to a known call — see WebhookEvent's "
    "docstring. Diagnostic only.",
)
async def list_webhook_events(
    limit: int = 50, session: AsyncSession = Depends(get_db)
) -> list[WebhookEventRead]:
    events = (
        (
            await session.execute(
                select(WebhookEvent).order_by(col(WebhookEvent.received_at).desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [WebhookEventRead.model_validate(e, from_attributes=True) for e in events]
