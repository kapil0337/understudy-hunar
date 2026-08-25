"""Deterministic, zero-credit sourcing provider backed by fixtures/candidates.json — 40
frontline profiles across Chennai, Bengaluru, Hyderabad and Pune. Always works, so it is both
the default provider and the fallback when PDL is unavailable (see app/services/sourcing.py).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.integrations.sourcing.base import SourcedCandidate, SourcingQuery, SourcingResult

DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "candidates.json"


@lru_cache(maxsize=1)
def _load(path: str) -> list[SourcedCandidate]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [SourcedCandidate.model_validate(entry) for entry in raw]


def _title_matches(candidate: SourcedCandidate, titles: list[str]) -> bool:
    if not titles:
        return True
    title = (candidate.current_title or "").lower()
    return any(t.lower() in title for t in titles)


def _skills_match(candidate: SourcedCandidate, skills: list[str]) -> bool:
    if not skills:
        return True
    candidate_skills = {s.lower() for s in candidate.skills}
    required = {s.lower() for s in skills}
    return bool(candidate_skills & required)


def _location_matches(candidate: SourcedCandidate, locations: list[str]) -> bool:
    if not locations:
        return True
    location = (candidate.location or "").lower()
    return any(loc.lower() in location for loc in locations)


def _meets_min_years(candidate: SourcedCandidate, min_years: float | None) -> bool:
    if min_years is None:
        return True
    return candidate.years_experience is not None and candidate.years_experience >= min_years


def _matches(candidate: SourcedCandidate, query: SourcingQuery) -> bool:
    return (
        _title_matches(candidate, query.titles)
        and _skills_match(candidate, query.skills)
        and _location_matches(candidate, query.locations)
        and _meets_min_years(candidate, query.min_years)
    )


class FixtureProvider:
    name = "fixtures"

    def __init__(self, fixture_path: Path = DEFAULT_FIXTURE_PATH) -> None:
        self._fixture_path = fixture_path

    async def search(self, query: SourcingQuery) -> SourcingResult:
        candidates = _load(str(self._fixture_path))
        matched = [c for c in candidates if _matches(c, query)]
        return SourcingResult(provider=self.name, candidates=matched[: query.limit], cached=False)

    async def aclose(self) -> None:
        return None
