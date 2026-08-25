"""Shared contract for candidate sourcing providers.

A provider turns a search query into a list of normalised candidate leads. It never returns a
usable phone number: per CLAUDE.md, phone_e164 is only ever set through the consent flow
(app/services/consent.py), regardless of which provider found the candidate. `needs_phone` is
therefore always True here — it exists so the UI can say "needs consent outreach" rather than
implying a number is already on file.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Language


class SourcingQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    min_years: float | None = None
    limit: int = Field(default=10, gt=0)


class SourcedCandidate(BaseModel):
    """What every provider returns, normalised. `raw` keeps the provider's own payload for that
    one candidate so an unexpected or partial shape is still inspectable, never guessed at."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str
    full_name: str
    headline: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    location: str | None = None
    skills: list[str] = Field(default_factory=list)
    years_experience: float | None = None
    linkedin_url: str | None = None
    preferred_language: Language | None = None
    has_phone_flag: bool = Field(
        default=False,
        description="Provider-reported hint that a phone number may exist on their side. Never "
        "a usable number — see module docstring.",
    )
    needs_phone: bool = Field(
        default=True,
        description="Always True: no provider in this system ever supplies a usable phone "
        "number, so every sourced candidate needs the consent flow before a call can be made.",
    )
    raw: dict[str, Any] = Field(default_factory=dict)


class SourcingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    candidates: list[SourcedCandidate]
    cached: bool = False


class SourcingError(Exception):
    """Base for every sourcing adapter failure."""


class SourcingAuthError(SourcingError):
    """The provider rejected our credentials. Triggers the fixtures fallback."""


class SourcingQuotaExceeded(SourcingError):
    """Out of credits or rate-limited. Triggers the fixtures fallback."""


class SourcingProviderError(SourcingError):
    """Any other provider failure that survived retries."""


@runtime_checkable
class SourcingProvider(Protocol):
    """What app/services/sourcing.py needs from a provider."""

    name: str

    async def search(self, query: SourcingQuery) -> SourcingResult: ...

    async def aclose(self) -> None: ...
