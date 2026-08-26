"""Ingest one inbound Hunar webhook. The route (app/api/routes/webhooks.py) stays thin: read
the raw request body and headers, call process_webhook, translate the outcome to a status code.

Steps, matching CONTRIBUTING.md:

  1. The caller reads raw bytes before parsing — process_webhook takes raw_body, not a parsed
     dict, because the signature is computed over those exact bytes; re-serialising parsed JSON
     changes whitespace/key order enough to break verification.
  2. Verify the signature. A failure is still persisted (signature_valid=False) but never
     applied — the route turns an invalid signature into a 401.
  3. The raw event is persisted unconditionally, valid or not, before anything else — see
     WebhookEvent's docstring: it is an append-only audit log, not a working table.
  4. Outreach is resolved by request_id first (the correlation key we assigned at call time),
     falling back to hunar_call_id. An id we don't recognise is logged and treated as accepted
     rather than an error — Hunar must not see a 4xx/5xx for a payload it has no way to fix, or
     it will retry forever.
  5. Idempotent on (call_id, event_type, status): a resent webhook is detected against prior
     *valid* WebhookEvent rows for the same call and not re-applied. (Only the `status` webhook
     carries a status value; the other three event types occur at most once per call in
     Hunar's model, so matching on (call_id, event_type) alone is the same check for them.)
  6. The actual field mutation goes through app/services/outreach.py's apply_*_webhook
     functions, which share the same status-precedence rule refresh_outreach's polling uses —
     so a webhook and a poll can never disagree about whether a call is allowed to move
     backward.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.integrations.hunar.models import (
    CallRecordingWebhook,
    CallResultWebhook,
    CallStatusWebhook,
    CallSummaryWebhook,
)
from app.integrations.hunar.signature import verify_webhook_signature
from app.models.outreach import Outreach
from app.models.webhook_event import WebhookEvent
from app.services.outreach import (
    apply_recording_webhook,
    apply_result_webhook,
    apply_status_webhook,
    apply_summary_webhook,
)

logger = structlog.get_logger()

WebhookKind = Literal["status", "recording", "result", "summary"]


@dataclass
class WebhookOutcome:
    signature_valid: bool
    event_id: uuid.UUID
    resolved: bool
    duplicate: bool
    applied: bool


async def process_webhook(
    session: AsyncSession,
    kind: WebhookKind,
    *,
    api_key: str,
    timestamp: str | None,
    signature_header: str | None,
    raw_body: bytes,
) -> WebhookOutcome:
    signature_valid = verify_webhook_signature(
        api_key, timestamp or "", raw_body, signature_header or ""
    )

    try:
        payload: dict[str, Any] = json.loads(raw_body) if raw_body else {}
    except ValueError:
        payload = {}

    call_id = payload.get("call_id")
    request_id = payload.get("request_id")
    event_type = payload.get("event_type") or f"call.{kind}"

    event = WebhookEvent(
        event_type=event_type,
        call_id=call_id if isinstance(call_id, str) else None,
        request_id=request_id if isinstance(request_id, str) else None,
        signature_valid=signature_valid,
        raw_payload=payload,
    )
    session.add(event)
    await session.flush()

    if not signature_valid:
        await session.commit()
        logger.warning("webhook_signature_invalid", event_type=event_type, call_id=call_id)
        return WebhookOutcome(
            signature_valid=False,
            event_id=event.id,
            resolved=False,
            duplicate=False,
            applied=False,
        )

    outreach = await _resolve_outreach(session, request_id, call_id)
    if outreach is None:
        await session.commit()
        logger.info(
            "webhook_unresolved", event_type=event_type, call_id=call_id, request_id=request_id
        )
        return WebhookOutcome(
            signature_valid=True, event_id=event.id, resolved=False, duplicate=False, applied=False
        )

    status_value = payload.get("status") if kind == "status" else None
    if await _is_duplicate(session, event.id, call_id, event_type, status_value):
        await session.commit()
        logger.info("webhook_duplicate_skipped", event_type=event_type, call_id=call_id)
        return WebhookOutcome(
            signature_valid=True, event_id=event.id, resolved=True, duplicate=True, applied=False
        )

    applied = _dispatch(kind, outreach, payload)
    session.add(outreach)
    await session.commit()
    return WebhookOutcome(
        signature_valid=True, event_id=event.id, resolved=True, duplicate=False, applied=applied
    )


async def _resolve_outreach(
    session: AsyncSession, request_id: Any, call_id: Any
) -> Outreach | None:
    if isinstance(request_id, str) and request_id:
        outreach = (
            await session.execute(select(Outreach).where(col(Outreach.request_id) == request_id))
        ).scalar_one_or_none()
        if outreach is not None:
            return outreach
    if isinstance(call_id, str) and call_id:
        return (
            await session.execute(select(Outreach).where(col(Outreach.hunar_call_id) == call_id))
        ).scalar_one_or_none()
    return None


async def _is_duplicate(
    session: AsyncSession,
    this_event_id: uuid.UUID,
    call_id: Any,
    event_type: str,
    status_value: Any,
) -> bool:
    if not isinstance(call_id, str) or not call_id:
        return False

    rows = (
        (
            await session.execute(
                select(WebhookEvent).where(
                    col(WebhookEvent.call_id) == call_id,
                    col(WebhookEvent.event_type) == event_type,
                    col(WebhookEvent.signature_valid).is_(True),
                    col(WebhookEvent.id) != this_event_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return any(row.raw_payload.get("status") == status_value for row in rows)


def _dispatch(kind: WebhookKind, outreach: Outreach, payload: dict[str, Any]) -> bool:
    if kind == "status":
        return apply_status_webhook(outreach, CallStatusWebhook.model_validate(payload))
    if kind == "recording":
        apply_recording_webhook(outreach, CallRecordingWebhook.model_validate(payload))
        return True
    if kind == "result":
        apply_result_webhook(outreach, CallResultWebhook.model_validate(payload))
        return True
    apply_summary_webhook(outreach, CallSummaryWebhook.model_validate(payload))
    return True
