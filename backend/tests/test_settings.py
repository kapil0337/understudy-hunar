from __future__ import annotations

import pytest


def test_get_settings_fails_loudly_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.settings import get_settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="database_url"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_capabilities_all_false_when_keys_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import get_settings

    monkeypatch.delenv("HUNAR_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("PDL_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.capabilities == {
            "hunar": False,
            "nvidia": False,
            "pdl": False,
            "gemini": False,
        }
    finally:
        get_settings.cache_clear()
