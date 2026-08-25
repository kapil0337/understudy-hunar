"""Deterministic candidate/job match scoring. No LLM call — every component here is a plain
function of the candidate and the compiled JD, so the result is reproducible and explainable,
never a black box (CLAUDE.md). MatchBreakdown carries each component with its weight so the UI
can render a segmented bar instead of a bare number.
"""

from __future__ import annotations

import difflib

from app.models.candidate import Candidate
from app.schemas.compiled_jd import CompiledJD
from app.schemas.ranking import MatchBreakdown, MatchComponent

_WEIGHTS: dict[str, float] = {
    "skill_overlap": 40.0,
    "title_similarity": 20.0,
    "location_match": 20.0,
    "experience_fit": 20.0,
}

_TITLE_SIMILARITY_FLOOR = 0.3  # ratios below this read as "no real match"; clamped to 0


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def score_skill_overlap(candidate_skills: list[str], must_have_skills: list[str]) -> float:
    """% of must-have skills the candidate lists, case-insensitively. No must-haves means
    nothing to fail on, so it scores full marks rather than 0/0."""
    if not must_have_skills:
        return 100.0

    candidate_set = {_normalise(s) for s in candidate_skills if isinstance(s, str)}
    required_set = {_normalise(s) for s in must_have_skills}
    overlap = candidate_set & required_set
    return 100.0 * len(overlap) / len(required_set)


def score_title_similarity(candidate_title: str | None, target_titles: list[str]) -> float:
    """Best fuzzy match of the candidate's current title against any target title. Empty
    target_titles means nothing to compare against, so it scores full marks."""
    if not target_titles:
        return 100.0
    if not candidate_title:
        return 0.0

    normalised_candidate = _normalise(candidate_title)
    best_ratio = max(
        difflib.SequenceMatcher(None, normalised_candidate, _normalise(target)).ratio()
        for target in target_titles
    )
    if best_ratio < _TITLE_SIMILARITY_FLOOR:
        return 0.0
    return best_ratio * 100.0


def score_location_match(candidate_location: str | None, target_locations: list[str]) -> float:
    """Substring match either direction, case-insensitive. Empty target_locations means no
    location constraint, so it scores full marks."""
    if not target_locations:
        return 100.0
    if not candidate_location:
        return 0.0

    normalised_candidate = _normalise(candidate_location)
    for target in target_locations:
        normalised_target = _normalise(target)
        if normalised_target in normalised_candidate or normalised_candidate in normalised_target:
            return 100.0
    return 0.0


def score_experience_fit(candidate_years: float | None, min_years: float | None) -> float:
    """Full marks at or above the requirement, linear falloff below it. No requirement means
    nothing to fail on, so it scores full marks. Missing candidate data cannot be verified as
    meeting the requirement, so it scores 0 rather than assuming a pass."""
    if min_years is None or min_years <= 0:
        return 100.0
    if candidate_years is None:
        return 0.0
    if candidate_years >= min_years:
        return 100.0
    return max(0.0, 100.0 * candidate_years / min_years)


def score_candidate(candidate: Candidate, compiled: CompiledJD) -> MatchBreakdown:
    candidate_skills = [s for s in candidate.skills if isinstance(s, str)]
    target_titles = [compiled.role_title, *compiled.search_query.titles]
    target_locations = compiled.search_query.locations or compiled.locations
    candidate_title = candidate.current_title or candidate.headline

    scores = {
        "skill_overlap": score_skill_overlap(candidate_skills, compiled.must_have_skills),
        "title_similarity": score_title_similarity(candidate_title, target_titles),
        "location_match": score_location_match(candidate.location, target_locations),
        "experience_fit": score_experience_fit(
            candidate.years_experience, compiled.min_years_experience
        ),
    }
    components = {
        name: MatchComponent(score=score, weight=_WEIGHTS[name]) for name, score in scores.items()
    }
    match_score = sum(c.score * c.weight for c in components.values()) / 100.0

    return MatchBreakdown(match_score=match_score, components=components)


def apply_match(candidate: Candidate, breakdown: MatchBreakdown) -> None:
    """Set match_score/match_breakdown on the candidate. Not persisted — the caller decides
    whether and when to save, same convention as jd_compiler.build_agent_version."""
    candidate.match_score = breakdown.match_score
    candidate.match_breakdown = breakdown.model_dump(mode="json")
