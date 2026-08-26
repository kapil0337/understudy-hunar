"""POST /webhooks/hunar/{kind}. Thin by design: read the raw body and headers, hand off to
app/services/webhooks.process_webhook, translate its outcome into a status code."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.db.session import get_db
from app.services.webhooks import WebhookKind, process_webhook

router = APIRouter(prefix="/webhooks/hunar", tags=["webhooks"])


@router.post(
    "/{kind}",
    summary="Receive a Hunar call-lifecycle webhook",
    description="`kind` is one of status|recording|result|summary. The signature is carried in "
    "the `X-Hunar-Signature` header, timed by `X-Hunar-Timestamp` (confirmed header names), and "
    "verified over the RAW request body (see app/integrations/hunar/signature.py). A request "
    "missing either header returns 400 naming the missing one; a present-but-wrong signature "
    "returns 401 and is never applied. An unrecognised call/request id is still accepted (200) "
    "and logged rather than erroring, since Hunar would otherwise retry a payload it has no way "
    "to fix.",
)
async def receive_hunar_webhook(
    kind: WebhookKind, request: Request, session: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    settings = get_settings()
    if not settings.hunar_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Hunar is not configured (HUNAR_API_KEY missing) — no key to verify a signature "
            "against.",
        )

    timestamp = request.headers.get("X-Hunar-Timestamp")
    if not timestamp:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing X-Hunar-Timestamp header")
    signature_header = request.headers.get("X-Hunar-Signature")
    if not signature_header:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing X-Hunar-Signature header")

    raw_body = await request.body()
    outcome = await process_webhook(
        session,
        kind,
        api_key=settings.hunar_api_key,
        timestamp=timestamp,
        signature_header=signature_header,
        raw_body=raw_body,
    )

    if not outcome.signature_valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook signature")

    return {
        "success": True,
        "resolved": outcome.resolved,
        "duplicate": outcome.duplicate,
        "applied": outcome.applied,
    }
