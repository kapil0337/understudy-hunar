from __future__ import annotations

import pytest

from app.core.settings import Settings


def _disable_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings reads backend/.env directly (pydantic-settings' dotenv source), independent of
    os.environ — deleting a key with monkeypatch.delenv alone does not hide it, since a fresh
    Settings() still finds it on disk. This must be disabled explicitly for a test to observe a
    key as truly absent. (tests/conftest.py disables it suite-wide too, as a safety net so no
    test can ever pick up a real DATABASE_URL; each test here does it again explicitly so its
    behaviour is provable in isolation, not dependent on that other file.)
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)


def test_get_settings_fails_loudly_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.settings import get_settings

    _disable_dotenv(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="database_url"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_capabilities_all_false_when_keys_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import get_settings

    _disable_dotenv(monkeypatch)
    monkeypatch.delenv("HUNAR_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("PDL_API_KEY", raising=False)
    monkeypatch.delenv("CORESIGNAL_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.capabilities == {
            "hunar": False,
            "nvidia": False,
            "pdl": False,
            "coresignal": False,
            "gemini": False,
        }
    finally:
        get_settings.cache_clear()
