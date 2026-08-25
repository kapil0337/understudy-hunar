from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env.

    DATABASE_URL is the only setting with no default: the app cannot do
    anything useful without a database, so it fails loudly at startup if
    that is missing. HUNAR_API_KEY, NVIDIA_API_KEY, and PDL_API_KEY are
    optional — the app boots without them and reports reduced capability,
    so a reviewer can run it with only a database.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = Field(
        description="Postgres DSN, e.g. postgresql+asyncpg://user:pass@host/db"
    )
    test_database_url: str | None = Field(
        default=None,
        description="Postgres DSN for the test suite only. Must differ from DATABASE_URL — "
        "the suite refuses to run against a database that could also be the real one.",
    )

    hunar_api_key: str | None = Field(
        default=None,
        description="Hunar Voice Agents API key. Server-side only, never sent to /web.",
    )
    nvidia_api_key: str | None = Field(
        default=None, description="NVIDIA API key. Server-side only, never sent to /web."
    )
    pdl_api_key: str | None = Field(default=None, description="People Data Labs API key")

    sourcing_provider: Literal["pdl", "fixtures"] = Field(
        default="fixtures",
        description="Which candidate sourcing provider to use. Falls back to fixtures at "
        "call time on a PDL auth or quota error regardless of this setting.",
    )
    channel: Literal["manual", "whatsapp"] = Field(
        default="manual",
        description="Which ConsentChannel implementation to use. WhatsApp is a documented "
        "seam only — see app/integrations/whatsapp/channel.py.",
    )
    gemini_api_key: str | None = Field(
        default=None, description="Google Gemini API key. Server-side only, never sent to /web."
    )

    # Per-role LLM routing: LLM_PROVIDER_<ROLE> / LLM_MODEL_<ROLE>, with a secondary used when
    # the primary is out of quota or otherwise failing. Roles are compiler | simulator.
    llm_provider_compiler: str = "nvidia"
    llm_model_compiler: str = "meta/llama-3.3-70b-instruct"
    llm_fallback_provider_compiler: str | None = "gemini"
    llm_fallback_model_compiler: str | None = "gemini-2.5-flash-lite"

    llm_provider_simulator: str = "nvidia"
    llm_model_simulator: str = "meta/llama-3.3-70b-instruct"
    llm_fallback_provider_simulator: str | None = "gemini"
    llm_fallback_model_simulator: str | None = "gemini-2.5-flash-lite"

    llm_cache_enabled: bool = Field(
        default=True,
        description="Cache LLM responses by sha256(role, model, messages, schema). On by "
        "default — per CLAUDE.md this is what makes iterating on the rehearsal loop affordable.",
    )

    demo_allowed_numbers: str = Field(
        default="", description="Comma-separated E.164 numbers permitted for outbound demo calls"
    )

    public_base_url: str | None = Field(
        default=None,
        description="Publicly reachable base URL for this service (e.g. an ngrok tunnel or "
        "deployed host), used to build the four Hunar callback_config URLs. Left unset in "
        "local dev has no correctness impact: callback_config is simply omitted from the call "
        "and app/services/outreach.refresh_outreach's polling is what keeps the board correct "
        "without webhooks ever arriving.",
    )

    @property
    def demo_allowed_numbers_list(self) -> list[str]:
        return [number.strip() for number in self.demo_allowed_numbers.split(",") if number.strip()]

    @property
    def capabilities(self) -> dict[str, bool]:
        """Which optional integrations are enabled given the current configuration."""
        return {
            "hunar": self.hunar_api_key is not None,
            "nvidia": self.nvidia_api_key is not None,
            "pdl": self.pdl_api_key is not None,
            "gemini": self.gemini_api_key is not None,
        }

    def llm_route(self, role: str) -> tuple[tuple[str, str], tuple[str, str] | None]:
        """Return ((primary_provider, primary_model), (fallback_provider, fallback_model) | None)
        for a role, read from LLM_PROVIDER_<ROLE> / LLM_MODEL_<ROLE> and their fallback twins."""
        try:
            primary = (
                getattr(self, f"llm_provider_{role}"),
                getattr(self, f"llm_model_{role}"),
            )
        except AttributeError as exc:
            raise ValueError(f"No LLM routing configured for role {role!r}") from exc

        provider = getattr(self, f"llm_fallback_provider_{role}", None)
        model = getattr(self, f"llm_fallback_model_{role}", None)
        fallback = (provider, model) if provider and model else None
        return primary, fallback


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = ", ".join(sorted({str(error["loc"][0]) for error in exc.errors()}))
        raise RuntimeError(
            f"Missing or invalid required setting(s): {missing}. "
            "Check your .env against .env.example."
        ) from exc
