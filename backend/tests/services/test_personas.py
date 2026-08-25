from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.job import Job
from app.models.persona import Persona
from app.schemas.compiled_jd import CompiledJD, KnockoutCriterion, ScreeningQuestion
from app.schemas.persona import ARCHETYPES, AnswerValue
from app.services.llm import InMemoryLLMCache, LLMService
from app.services.personas import (
    PersonaGenerationError,
    evaluate_knockouts,
    generate_personas,
    get_or_regenerate_personas,
)
from tests.services.conftest import JD_NAMES, FakeProvider, load_compiled_fixture

pytestmark = pytest.mark.parametrize("jd_name", JD_NAMES)


def compiled_from_fixture(jd_name: str) -> CompiledJD:
    return CompiledJD.model_validate(load_compiled_fixture(jd_name))


# --------------------------------------------------------------- building scripted responses


def _candidates(question: ScreeningQuestion, target: KnockoutCriterion) -> list[AnswerValue]:
    if question.answer_type == "boolean":
        return [True, False]
    if question.answer_type == "number":
        value = float(target.value) if isinstance(target.value, int | float) else 0.0
        return [value, value - 1, value + 1]
    if question.answer_type == "enum":
        return list(question.options or [])
    values = target.value if isinstance(target.value, list) else [target.value]
    return [str(v) for v in values] or ["free text"]


def _qualifying_answers(compiled: CompiledJD) -> dict[str, AnswerValue]:
    """One safe value per question: for every knockout on that question, whichever candidate
    does not make evaluate_knockouts fire."""
    answers: dict[str, AnswerValue] = {}
    for question in compiled.screening_questions:
        relevant = [c for c in compiled.knockout_criteria if c.question_id == question.id]
        if not relevant:
            answers[question.id] = (
                list(question.options or [])[0]
                if question.answer_type == "enum"
                else _default(question)
            )
            continue
        for candidate in _candidates(question, relevant[0]):
            trial = {**answers, question.id: candidate}
            if evaluate_knockouts(relevant, trial):
                answers[question.id] = candidate
                break
        else:
            raise AssertionError(f"no safe value found for {question.id}")
    return answers


def _default(question: ScreeningQuestion) -> AnswerValue:
    if question.answer_type == "boolean":
        return True
    if question.answer_type == "number":
        return 5.0
    return "A representative free-text answer."


def _disqualifying_answers(compiled: CompiledJD) -> dict[str, AnswerValue]:
    """Same as _qualifying_answers, but the first knockout's question is deliberately flipped
    to fire, so the resulting set is unambiguously unqualified."""
    answers = _qualifying_answers(compiled)
    if not compiled.knockout_criteria:
        return answers
    target = compiled.knockout_criteria[0]
    question = next(q for q in compiled.screening_questions if q.id == target.question_id)
    for candidate in _candidates(question, target):
        trial = {**answers, question.id: candidate}
        if not evaluate_knockouts([target], trial):
            answers[question.id] = candidate
            return answers
    raise AssertionError(f"no disqualifying value found for {question.id}")


def _persona_draft(
    archetype: str,
    answers: dict[str, AnswerValue],
    *,
    interested: bool = True,
    verbosity: str = "normal",
    cooperativeness: str = "cooperative",
    language_switching: bool = False,
    off_script_questions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "archetype": archetype,
        "profile": {
            "name": f"{archetype.title().replace('_', ' ')} Candidate",
            "background": "Has held similar jobs in the area for a couple of years.",
            "years_experience": 2.0,
            "skills": ["general labour"],
            "situation": "Currently unemployed and actively looking.",
            "location": "Nearby",
            "language": "ENGLISH",
        },
        "ground_truth_answers": answers,
        "expected_interested": interested,
        "behaviour": {
            "verbosity": verbosity,
            "cooperativeness": cooperativeness,
            "language_switching": language_switching,
            "off_script_questions": off_script_questions or [],
        },
    }


def build_persona_payload(
    compiled: CompiledJD, *, unqualified_archetype_ok: bool = True
) -> dict[str, Any]:
    qualifying = _qualifying_answers(compiled)
    unqualified_answers = (
        _disqualifying_answers(compiled) if unqualified_archetype_ok else qualifying
    )

    return {
        "personas": [
            _persona_draft("QUALIFIED_EAGER", qualifying, verbosity="verbose"),
            _persona_draft("QUALIFIED_TERSE", qualifying, verbosity="terse"),
            _persona_draft("UNQUALIFIED_CLEAR", unqualified_answers, interested=False),
            _persona_draft("SALARY_FIRST", qualifying, off_script_questions=["What does it pay?"]),
            _persona_draft("CODE_SWITCHER", qualifying, language_switching=True),
            _persona_draft("BUSY_HOSTILE", qualifying, interested=False, cooperativeness="hostile"),
        ]
    }


def service_returning(payload: dict[str, Any], settings: object) -> LLMService:
    nvidia = FakeProvider("nvidia", [json.dumps(payload)])
    return LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=settings,  # type: ignore[arg-type]
    )


# -------------------------------------------------------------------- evaluate_knockouts()


async def test_evaluate_knockouts_true_when_no_criteria_fire(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    answers = _qualifying_answers(compiled)

    assert evaluate_knockouts(compiled.knockout_criteria, answers) is True


async def test_evaluate_knockouts_false_when_a_criterion_fires(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    if not compiled.knockout_criteria:
        pytest.skip("fixture has no knockout criteria")
    answers = _disqualifying_answers(compiled)

    assert evaluate_knockouts(compiled.knockout_criteria, answers) is False


async def test_evaluate_knockouts_skips_missing_answer(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    if not compiled.knockout_criteria:
        pytest.skip("fixture has no knockout criteria")

    assert evaluate_knockouts(compiled.knockout_criteria, {}) is True


# -------------------------------------------------------------------- generate_personas()


async def test_generate_personas_returns_exactly_six_archetypes(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    service = service_returning(build_persona_payload(compiled), llm_settings)

    personas = await generate_personas(compiled, llm=service)

    assert sorted(p.archetype for p in personas) == sorted(ARCHETYPES)


async def test_generate_personas_ground_truth_covers_every_question(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    service = service_returning(build_persona_payload(compiled), llm_settings)

    personas = await generate_personas(compiled, llm=service)

    question_ids = {q.id for q in compiled.screening_questions}
    for persona in personas:
        assert question_ids <= persona.ground_truth.keys()
        assert "interested" in persona.ground_truth
        assert "qualified" in persona.ground_truth


async def test_generate_personas_qualified_eager_and_terse_are_qualified(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    service = service_returning(build_persona_payload(compiled), llm_settings)

    personas = await generate_personas(compiled, llm=service)

    by_archetype = {p.archetype: p for p in personas}
    assert by_archetype["QUALIFIED_EAGER"].ground_truth["qualified"] is True
    assert by_archetype["QUALIFIED_TERSE"].ground_truth["qualified"] is True


async def test_generate_personas_unqualified_clear_is_not_qualified(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    if not compiled.knockout_criteria:
        pytest.skip("fixture has no knockout criteria to fail")
    service = service_returning(build_persona_payload(compiled), llm_settings)

    personas = await generate_personas(compiled, llm=service)

    by_archetype = {p.archetype: p for p in personas}
    assert by_archetype["UNQUALIFIED_CLEAR"].ground_truth["qualified"] is False


async def test_generate_personas_qualified_is_computed_not_taken_from_the_model(
    jd_name: str, llm_settings: object
) -> None:
    """qualified must match what evaluate_knockouts computes from the answers, regardless of
    what expected_interested (the model's own flavour judgement) says."""
    compiled = compiled_from_fixture(jd_name)
    service = service_returning(build_persona_payload(compiled), llm_settings)

    personas = await generate_personas(compiled, llm=service)

    for persona in personas:
        answers = {
            question.id: persona.ground_truth[question.id]
            for question in compiled.screening_questions
        }
        assert persona.ground_truth["qualified"] == evaluate_knockouts(
            compiled.knockout_criteria, answers
        )


async def test_generate_personas_job_id_is_attached_when_given(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    service = service_returning(build_persona_payload(compiled), llm_settings)
    job_id = "11111111-1111-1111-1111-111111111111"

    personas = await generate_personas(compiled, job_id=job_id, llm=service)

    assert all(p.job_id == job_id for p in personas)


async def test_generate_personas_rejects_missing_archetype(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    payload = build_persona_payload(compiled)
    # Duplicate QUALIFIED_EAGER over BUSY_HOSTILE so the archetype set is no longer exact.
    payload["personas"][-1] = dict(payload["personas"][0])
    service = service_returning(payload, llm_settings)

    with pytest.raises(PersonaGenerationError, match="expected exactly the personas"):
        await generate_personas(compiled, llm=service)


async def test_generate_personas_rejects_answer_of_the_wrong_type(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    payload = build_persona_payload(compiled)
    boolean_question = next(q for q in compiled.screening_questions if q.answer_type == "boolean")
    payload["personas"][0]["ground_truth_answers"][boolean_question.id] = "yes"
    service = service_returning(payload, llm_settings)

    with pytest.raises(PersonaGenerationError, match=boolean_question.id):
        await generate_personas(compiled, llm=service)


async def test_generate_personas_rejects_qualified_eager_that_fails_a_knockout(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    if not compiled.knockout_criteria:
        pytest.skip("fixture has no knockout criteria to violate")
    payload = build_persona_payload(compiled)
    payload["personas"][0]["ground_truth_answers"] = _disqualifying_answers(compiled)
    service = service_returning(payload, llm_settings)

    with pytest.raises(PersonaGenerationError, match="QUALIFIED_EAGER"):
        await generate_personas(compiled, llm=service)


async def test_generate_personas_rejects_unqualified_clear_that_actually_qualifies(
    jd_name: str, llm_settings: object
) -> None:
    compiled = compiled_from_fixture(jd_name)
    if not compiled.knockout_criteria:
        pytest.skip("fixture has no knockout criteria")
    payload = build_persona_payload(compiled)
    payload["personas"][2]["ground_truth_answers"] = _qualifying_answers(compiled)
    service = service_returning(payload, llm_settings)

    with pytest.raises(PersonaGenerationError, match="UNQUALIFIED_CLEAR"):
        await generate_personas(compiled, llm=service)


# --------------------------------------------------------------- get_or_regenerate_personas()


async def test_get_or_regenerate_personas_persists_six_rows(
    jd_name: str, llm_settings: object, db_session: AsyncSession
) -> None:
    job = Job(title="x", raw_jd="irrelevant")
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)
    service = service_returning(build_persona_payload(compiled), llm_settings)

    personas = await get_or_regenerate_personas(db_session, job.id, compiled, llm=service)

    assert len(personas) == 6
    assert all(p.id is not None for p in personas)


async def test_get_or_regenerate_personas_reuses_existing_without_calling_the_llm(
    jd_name: str, llm_settings: object, db_session: AsyncSession
) -> None:
    job = Job(title="x", raw_jd="irrelevant")
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)
    service = service_returning(build_persona_payload(compiled), llm_settings)

    first = await get_or_regenerate_personas(db_session, job.id, compiled, llm=service)

    empty_service = LLMService(providers={}, cache=InMemoryLLMCache(), settings=llm_settings)  # type: ignore[arg-type]
    second = await get_or_regenerate_personas(db_session, job.id, compiled, llm=empty_service)

    assert {p.id for p in first} == {p.id for p in second}


async def test_get_or_regenerate_personas_replaces_on_explicit_flag(
    jd_name: str, llm_settings: object, db_session: AsyncSession
) -> None:
    job = Job(title="x", raw_jd="irrelevant")
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)
    service = service_returning(build_persona_payload(compiled), llm_settings)

    first = await get_or_regenerate_personas(db_session, job.id, compiled, llm=service)

    service_2 = service_returning(build_persona_payload(compiled), llm_settings)
    second = await get_or_regenerate_personas(
        db_session, job.id, compiled, llm=service_2, regenerate=True
    )

    assert {p.id for p in first}.isdisjoint({p.id for p in second})
    assert len(second) == 6

    remaining = (
        (await db_session.execute(select(Persona).where(col(Persona.job_id) == job.id)))
        .scalars()
        .all()
    )
    assert len(remaining) == 6
