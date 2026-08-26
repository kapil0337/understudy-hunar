"""Thin route-wiring tests: header parsing, status codes, settings check. The deep logic
(idempotency, status precedence, dispatch per kind) is already exercised directly against
app/services/webhooks.py in tests/services/test_webhooks.py."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.routes.webhooks as webhooks_module
from app.core.settings import Settings
from app.models.agent_version import AgentVersion
from app.models.candidate import Candidate
from app.models.enums import AgentVersionOrigin, CallStatus, Language
from app.models.job import Job
from app.models.outreach import Outreach
from tests.integrations.conftest import load_fixture

API_KEY = "test-key-not-a-real-credential"
FIXTURE_REQUEST_ID = "job1234-cand5678-a1"
FIXTURE_CALL_ID = "cal_00000000000000000000000001"


def _sign(api_key: str, timestamp: str, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return base64.b64encode(hmac.new(api_key.encode(), message, hashlib.sha256).digest()).decode()


@pytest.fixture(autouse=True)
def _configure_hunar_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused", hunar_api_key=API_KEY
    )
    monkeypatch.setattr(webhooks_module, "get_settings", lambda: settings)


async def _make_outreach(session: AsyncSession) -> Outreach:
    job = Job(title="x", raw_jd="raw jd text")
    session.add(job)
    await session.flush()

    candidate = Candidate(
        job_id=job.id,
        source_provider="fixtures",
        source_ref="fx_001",
        full_name="Test Candidate",
        skills=[],
        raw_payload={},
    )
    session.add(candidate)
    await session.flush()

    version = AgentVersion(
        job_id=job.id,
        version_no=1,
        language=Language.ENGLISH,
        voice_persona="NEHA",
        persona_name="Neha",
        agent_prompt="p",
        objective="o",
        introduction="i",
        result_prompt="r",
        result_schema={},
        hunar_agent_id="agt_1",
        origin=AgentVersionOrigin.COMPILED,
    )
    session.add(version)
    await session.flush()

    outreach = Outreach(
        candidate_id=candidate.id,
        agent_version_id=version.id,
        hunar_call_id=FIXTURE_CALL_ID,
        request_id=FIXTURE_REQUEST_ID,
        status=CallStatus.INITIATED,
        lifecycle_status="QUEUED",
    )
    session.add(outreach)
    await session.flush()
    return outreach


async def test_valid_status_webhook_is_applied(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _make_outreach(db_session)
    payload = load_fixture("webhook_call_status.json")
    raw_body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))

    resp = await api_client.post(
        "/webhooks/hunar/status",
        content=raw_body,
        headers={
            "X-Hunar-Timestamp": timestamp,
            "X-Hunar-Signature": _sign(API_KEY, timestamp, raw_body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["resolved"] is True
    assert body["applied"] is True


async def test_invalid_signature_returns_401(api_client: httpx.AsyncClient) -> None:
    payload = load_fixture("webhook_call_status.json")
    raw_body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))

    resp = await api_client.post(
        "/webhooks/hunar/status",
        content=raw_body,
        headers={
            "X-Hunar-Timestamp": timestamp,
            "X-Hunar-Signature": _sign("wrong-key", timestamp, raw_body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


async def test_missing_timestamp_header_returns_400(api_client: httpx.AsyncClient) -> None:
    payload = load_fixture("webhook_call_status.json")
    raw_body = json.dumps(payload).encode()

    resp = await api_client.post(
        "/webhooks/hunar/status",
        content=raw_body,
        headers={
            "X-Hunar-Signature": _sign(API_KEY, "1", raw_body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400
    assert "X-Hunar-Timestamp" in resp.json()["message"]


async def test_missing_signature_header_returns_400(api_client: httpx.AsyncClient) -> None:
    payload = load_fixture("webhook_call_status.json")
    raw_body = json.dumps(payload).encode()

    resp = await api_client.post(
        "/webhooks/hunar/status",
        content=raw_body,
        headers={
            "X-Hunar-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400
    assert "X-Hunar-Signature" in resp.json()["message"]


async def test_unresolved_call_is_still_accepted(api_client: httpx.AsyncClient) -> None:
    payload = load_fixture("webhook_call_status.json")  # no matching outreach row seeded
    raw_body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))

    resp = await api_client.post(
        "/webhooks/hunar/status",
        content=raw_body,
        headers={
            "X-Hunar-Timestamp": timestamp,
            "X-Hunar-Signature": _sign(API_KEY, timestamp, raw_body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["resolved"] is False


async def test_hunar_not_configured_returns_503(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured = Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused", hunar_api_key=None
    )
    monkeypatch.setattr(webhooks_module, "get_settings", lambda: unconfigured)

    resp = await api_client.post("/webhooks/hunar/status", json={})
    assert resp.status_code == 503
