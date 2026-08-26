"""Thin route-wiring tests for GET /internal/process-jobs — the serverless (Vercel) replacement
for app/worker.py's poll loop, see app/api/routes/internal.py. Only the auth gate is covered
here; draining itself is covered directly against a real connection in
tests/services/test_job_runner.py — this route's api_client fixture runs on a
savepoint-isolated session, but process_jobs() always opens its own real connection (by design,
same as app/worker.py's loop always has), which that fixture's isolation can't see into, so a
job enqueued through api_client would never appear processed even if this route worked
perfectly. The job-processing logic itself is also exercised via app/services/job_runner.py's
handlers in test_jobs_api.py and test_rehearsal_api.py (through run_pending_background_job)."""

from __future__ import annotations

import httpx
import pytest

import app.api.routes.internal as internal_module
from app.core.settings import Settings

SECRET = "test-cron-secret-not-a-real-credential"


def _settings(cron_secret: str | None) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        cron_secret=cron_secret,
    )


async def test_process_jobs_404s_when_cron_secret_not_configured(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(internal_module, "get_settings", lambda: _settings(None))
    resp = await api_client.get("/internal/process-jobs")
    assert resp.status_code == 404


async def test_process_jobs_401s_without_a_secret(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(internal_module, "get_settings", lambda: _settings(SECRET))
    resp = await api_client.get("/internal/process-jobs")
    assert resp.status_code == 401


async def test_process_jobs_401s_with_the_wrong_secret(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(internal_module, "get_settings", lambda: _settings(SECRET))
    resp = await api_client.get("/internal/process-jobs", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
