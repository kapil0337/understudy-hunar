from __future__ import annotations

import uuid

from app.models.candidate import Candidate
from app.schemas.compiled_jd import CompiledJD
from app.services.ranking import (
    apply_match,
    score_candidate,
    score_experience_fit,
    score_location_match,
    score_skill_overlap,
    score_title_similarity,
)
from tests.services.conftest import load_compiled_fixture


def _compiled(name: str) -> CompiledJD:
    return CompiledJD.model_validate(load_compiled_fixture(name))


def _candidate(**overrides: object) -> Candidate:
    defaults: dict[str, object] = {
        "job_id": uuid.uuid4(),
        "source_provider": "fixtures",
        "source_ref": "fx_001",
        "full_name": "Test Candidate",
        "skills": [],
        "raw_payload": {},
    }
    defaults.update(overrides)
    return Candidate(**defaults)


# --------------------------------------------------------------------- score_skill_overlap


def test_skill_overlap_full_match() -> None:
    assert score_skill_overlap(["A", "B", "C"], ["a", "b"]) == 100.0


def test_skill_overlap_partial_match() -> None:
    assert score_skill_overlap(["A"], ["a", "b"]) == 50.0


def test_skill_overlap_no_must_haves_scores_full_marks() -> None:
    assert score_skill_overlap([], []) == 100.0


def test_skill_overlap_no_overlap_scores_zero() -> None:
    assert score_skill_overlap(["x", "y"], ["a", "b"]) == 0.0


# ------------------------------------------------------------------ score_title_similarity


def test_title_similarity_exact_match() -> None:
    assert score_title_similarity("Delivery Rider", ["Delivery Rider"]) == 100.0


def test_title_similarity_no_targets_scores_full_marks() -> None:
    assert score_title_similarity("Anything", []) == 100.0


def test_title_similarity_missing_candidate_title_scores_zero() -> None:
    assert score_title_similarity(None, ["Delivery Rider"]) == 0.0


def test_title_similarity_unrelated_title_scores_zero() -> None:
    assert score_title_similarity("Software Engineer", ["Delivery Rider"]) == 0.0


# -------------------------------------------------------------------- score_location_match


def test_location_match_exact() -> None:
    assert score_location_match("Chennai", ["Chennai"]) == 100.0


def test_location_match_case_insensitive_substring() -> None:
    assert score_location_match("chennai, tamil nadu", ["Chennai"]) == 100.0


def test_location_match_no_targets_scores_full_marks() -> None:
    assert score_location_match("Anywhere", []) == 100.0


def test_location_match_missing_candidate_location_scores_zero() -> None:
    assert score_location_match(None, ["Chennai"]) == 0.0


def test_location_match_mismatch_scores_zero() -> None:
    assert score_location_match("Pune", ["Chennai"]) == 0.0


# ------------------------------------------------------------------- score_experience_fit


def test_experience_fit_meets_requirement() -> None:
    assert score_experience_fit(5, 3) == 100.0


def test_experience_fit_no_requirement_scores_full_marks() -> None:
    assert score_experience_fit(0, None) == 100.0
    assert score_experience_fit(None, 0) == 100.0


def test_experience_fit_missing_candidate_data_scores_zero() -> None:
    assert score_experience_fit(None, 2) == 0.0


def test_experience_fit_below_requirement_is_linear() -> None:
    assert score_experience_fit(1, 2) == 50.0


# --------------------------------------------------------------------------- score_candidate


def test_score_candidate_strong_match_scores_highly() -> None:
    compiled = _compiled("delivery_rider_chennai")
    candidate = _candidate(
        current_title="Delivery Rider",
        location="Chennai",
        skills=["two-wheeler riding", "smartphone use", "city navigation"],
        years_experience=3,
    )

    breakdown = score_candidate(candidate, compiled)

    assert breakdown.match_score > 90.0
    assert set(breakdown.components) == {
        "skill_overlap",
        "title_similarity",
        "location_match",
        "experience_fit",
    }
    assert sum(c.weight for c in breakdown.components.values()) == 100.0


def test_score_candidate_weak_match_scores_lowly() -> None:
    # retail_associate_bengaluru has a nonzero min_years_experience, unlike
    # delivery_rider_chennai's 0 — so a mismatch on every axis actually fails all four
    # components rather than getting a free pass on experience_fit.
    compiled = _compiled("retail_associate_bengaluru")
    candidate = _candidate(
        current_title="Software Engineer",
        location="Pune",
        skills=["python"],
        years_experience=None,
    )

    breakdown = score_candidate(candidate, compiled)

    assert breakdown.match_score < 20.0


def test_apply_match_sets_candidate_fields() -> None:
    compiled = _compiled("retail_associate_bengaluru")
    candidate = _candidate(
        current_title="Retail Sales Associate",
        location="Bengaluru",
        skills=["customer service", "billing", "spoken Kannada", "spoken English"],
        years_experience=2,
    )

    breakdown = score_candidate(candidate, compiled)
    apply_match(candidate, breakdown)

    assert candidate.match_score == breakdown.match_score
    assert candidate.match_breakdown is not None
    assert candidate.match_breakdown["match_score"] == breakdown.match_score
