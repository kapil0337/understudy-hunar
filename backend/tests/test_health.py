from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings, get_settings


def test_healthz_reports_ok_and_capabilities(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Settings reads backend/.env directly, independent of os.environ, so the real keys there
    # must be excluded explicitly rather than assumed absent — see test_settings.py's
    # _disable_dotenv for why monkeypatch.delenv alone would not be enough.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("HUNAR_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("PDL_API_KEY", raising=False)
    monkeypatch.delenv("CORESIGNAL_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        response = client.get("/healthz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["capabilities"] == {
            "hunar": False,
            "nvidia": False,
            "pdl": False,
            "coresignal": False,
            "gemini": False,
            "groq": False,
        }
    finally:
        get_settings.cache_clear()
