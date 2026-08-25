"""Tests for jd_compiler helpers that don't depend on a specific JD fixture.

Kept out of test_jd_compiler.py because that module is parametrized over all three JD fixtures
via a module-level pytestmark — these tests would either run redundantly three times or clash
with that parametrization.
"""

from __future__ import annotations

import pytest

from app.models.enums import Language
from app.schemas.compiled_jd import CompiledJD
from app.services.jd_compiler import (
    find_document_dependent_questions,
    infer_languages_from_locations,
)
from tests.services.conftest import load_compiled_fixture

# ------------------------------------------------------------------- language inference


def test_chennai_infers_tamil() -> None:
    assert Language.TAMIL in infer_languages_from_locations(["Chennai"])


def test_bengaluru_infers_kannada() -> None:
    assert Language.KANNADA in infer_languages_from_locations(["Bengaluru"])


def test_pune_infers_marathi() -> None:
    assert Language.MARATHI in infer_languages_from_locations(["Pune"])


def test_always_includes_english_and_hindi_fallback() -> None:
    langs = infer_languages_from_locations(["Chennai"])
    assert Language.ENGLISH in langs
    assert Language.HINDI in langs


def test_unknown_location_still_gets_fallback_languages() -> None:
    assert infer_languages_from_locations(["Some Unmapped Town"]) == [
        Language.ENGLISH,
        Language.HINDI,
    ]


def test_no_duplicate_languages_across_multiple_locations() -> None:
    langs = infer_languages_from_locations(["Chennai", "Coimbatore"])
    assert len(langs) == len(set(langs))


def test_empty_locations_still_returns_fallback() -> None:
    assert infer_languages_from_locations([]) == [Language.ENGLISH, Language.HINDI]


# ------------------------------------------------------------- document-dependent heuristic


def _compiled_with_first_question_text(text: str) -> CompiledJD:
    compiled = CompiledJD.model_validate(load_compiled_fixture("delivery_rider_chennai"))
    questions = list(compiled.screening_questions)
    questions[0] = questions[0].model_copy(update={"text": text})
    return compiled.model_copy(update={"screening_questions": questions})


@pytest.mark.parametrize(
    "text",
    [
        "Please upload your Aadhaar card.",
        "What is your certificate number?",
        "Can you email me your resume?",
        "What is your exact date of birth?",
        "Please send your bank statement.",
        "Please attach your driving licence.",
    ],
)
def test_flags_document_dependent_phrasing(text: str) -> None:
    compiled = _compiled_with_first_question_text(text)

    offenders = find_document_dependent_questions(compiled)

    assert compiled.screening_questions[0].id in offenders


@pytest.mark.parametrize(
    "text",
    [
        "Do you have your own two-wheeler?",
        "How many years of experience do you have?",
        "Are you comfortable working night shifts?",
        "Which shift do you prefer, morning or evening?",
    ],
)
def test_does_not_flag_normal_questions(text: str) -> None:
    compiled = _compiled_with_first_question_text(text)

    assert find_document_dependent_questions(compiled) == []
