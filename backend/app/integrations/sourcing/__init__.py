"""Candidate sourcing adapters.

Two providers share the SourcingProvider protocol: PDLProvider (a real, rate-limited HTTP call
to People Data Labs) and FixtureProvider (a deterministic, zero-credit local dataset). Neither
ever returns a usable phone number — see base.py's module docstring. app/services/sourcing.py
sits on top and owns provider selection, provider_cache, and the auth/quota fallback to fixtures.
"""

from app.integrations.sourcing.base import (
    SourcedCandidate,
    SourcingAuthError,
    SourcingError,
    SourcingProvider,
    SourcingProviderError,
    SourcingQuery,
    SourcingQuotaExceeded,
    SourcingResult,
)
from app.integrations.sourcing.fixtures import FixtureProvider
from app.integrations.sourcing.pdl import PDLProvider

__all__ = [
    "FixtureProvider",
    "PDLProvider",
    "SourcedCandidate",
    "SourcingAuthError",
    "SourcingError",
    "SourcingProvider",
    "SourcingProviderError",
    "SourcingQuery",
    "SourcingQuotaExceeded",
    "SourcingResult",
]
