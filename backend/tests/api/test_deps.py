"""Unit tests for app/api/deps.py against controlled Settings instances — deliberately not
through the app/TestClient, since get_settings() reads the real .env file and this must stay
correct regardless of whether HUNAR_API_KEY happens to be set in the local environment."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import deps
from app.core.settings import Settings
from app.integrations.hunar.client import HunarClient


def _settings(hunar_api_key: str | None) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        hunar_api_key=hunar_api_key,
    )


async def test_get_hunar_client_raises_503_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: _settings(None))

    with pytest.raises(HTTPException) as excinfo:
        async for _ in deps.get_hunar_client():
            pass
    assert excinfo.value.status_code == 503


async def test_get_hunar_client_yields_client_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: _settings("test-key-not-a-real-credential"))

    async for client in deps.get_hunar_client():
        assert isinstance(client, HunarClient)


async def test_get_optional_hunar_client_yields_none_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: _settings(None))

    async for client in deps.get_optional_hunar_client():
        assert client is None


async def test_get_optional_hunar_client_yields_client_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: _settings("test-key-not-a-real-credential"))

    async for client in deps.get_optional_hunar_client():
        assert isinstance(client, HunarClient)
