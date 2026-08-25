from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.integrations.llm.base import LLMResponse
from app.models.enums import Language
from app.schemas.compiled_jd import CompiledJD, KnockoutCriterion, ScreeningQuestion, SearchQuery
from app.schemas.rehearsal import (
    CaseInput,
    CoverageCase,
    CoverageResult,
    EfficiencyCase,
    EfficiencyResult,
    FaithfulnessCase,
    FaithfulnessResult,
    FaithfulnessViolation,
    TranscriptTurn,
)
from app.services.llm import InMemoryLLMCache, LLMService
from app.services.rehearsal.score import (
    EFFICIENCY_FLAG_SECONDS,
    EFFICIENCY_TARGET_SECONDS,
    ScoringError,
    compute_composite,
    score_coverage,
    score_efficiency,
    score_extraction_accuracy,
    score_faithfulness,
    score_rehearsal_run,
)

# ------------------------------------------------------------------------------- a compiled JD
#
# Deliberately hand-built rather than one of the three fixture JDs: this needs a free_text
# question (none of the fixtures have one) and a short, exact 4-question list so "question 3"
# is unambiguous for the required skip/fabrication test below.


def _compiled() -> CompiledJD:
    return CompiledJD(
        role_title="Warehouse Associate",
        seniority="entry",
        employment_type="full_time",
        must_have_skills=["lifting"],
        nice_to_have_skills=[],
        min_years_experience=0,
        locations=["Pune"],
        shift_pattern="Day shift, six days a week",
        salary_range="Rs 15,000 - Rs 18,000 per month",
        candidate_languages=[Language.ENGLISH, Language.HINDI],
        screening_questions=[
            ScreeningQuestion(
                id="can_lift_15kg",
                text="Can you lift 15 kilos repeatedly through a shift?",
                answer_type="boolean",
                why_it_matters="Core physical requirement.",
            ),
            ScreeningQuestion(
                id="has_id_proof",
                text="Do you have a valid government ID?",
                answer_type="boolean",
                why_it_matters="Required for site access.",
            ),
            ScreeningQuestion(
                id="availability",
                text="Which days can you start?",
                answer_type="free_text",
                why_it_matters="Scheduling.",
            ),
            ScreeningQuestion(
                id="years_experience",
                text="How many years of warehouse experience do you have?",
                answer_type="number",
                why_it_matters="Screening.",
            ),
        ],
        knockout_criteria=[
            KnockoutCriterion(question_id="can_lift_15kg", operator="eq", value=False),
        ],
        facts_the_agent_may_state=[
            "The role is Warehouse Associate in Pune.",
            "Pay is Rs 15,000 to Rs 18,000 per month.",
            "Shift is day shift, six days a week.",
        ],
        search_query=SearchQuery(
            titles=["Warehouse Associate"], skills=["lifting"], locations=["Pune"], min_years=0
        ),
    )


def _case(**overrides: Any) -> CaseInput:
    ground_truth = {
        "can_lift_15kg": True,
        "has_id_proof": True,
        "availability": "Weekdays, starting Monday",
        "years_experience": 2.0,
        "interested": True,
        "qualified": True,
    }
    extracted_result = {k: v for k, v in ground_truth.items() if k != "interested"}
    defaults: dict[str, Any] = {
        "persona_id": uuid.uuid4(),
        "archetype": "QUALIFIED_EAGER",
        "ground_truth": ground_truth,
        "off_script_questions": [],
        "transcript": [TranscriptTurn(speaker="agent", text="Hello.", turn=0)],
        "extracted_result": extracted_result,
        "estimated_seconds": 60.0,
        "turn_count": 1,
    }
    defaults.update(overrides)
    return CaseInput(**defaults)


class _JudgeProvider:
    """Returns a scripted response keyed by schema_name (the judge's response-model class
    name) rather than call order — score_rehearsal_run runs the coverage and faithfulness
    judges concurrently via asyncio.gather, so a plain FIFO fake can't be scripted
    deterministically per-judge."""

    name = "nvidia"

    def __init__(self, responses_by_schema: dict[str, Any]) -> None:
        self.responses_by_schema = responses_by_schema
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, model: str, messages: list[dict[str, str]], temperature: float
    ) -> LLMResponse:
        raise AssertionError("score.py should only ever call structured_complete")

    async def structured_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> LLMResponse:
        self.calls.append({"schema_name": schema_name, "messages": messages})
        return LLMResponse(
            text=json.dumps(self.responses_by_schema[schema_name]), model=model, provider=self.name
        )

    async def aclose(self) -> None:
        pass


def _service_with(
    responses_by_schema: dict[str, Any], settings: object
) -> tuple[LLMService, _JudgeProvider]:
    provider = _JudgeProvider(responses_by_schema)
    service = LLMService(
        providers={"nvidia": provider},
        cache=InMemoryLLMCache(),
        settings=settings,  # type: ignore[arg-type]
    )
    return service, provider


# --------------------------------------------------------------------------- extraction_accuracy


def test_extraction_accuracy_is_100_when_everything_matches() -> None:
    compiled = _compiled()
    case = _case()

    result = score_extraction_accuracy(compiled, [case])

    assert result.score == 100.0
    assert all(f.correct for f in result.fields)
    # One field per screening question, plus `qualified`.
    assert len(result.fields) == len(compiled.screening_questions) + 1


def test_extraction_accuracy_flags_a_wrong_boolean_field() -> None:
    compiled = _compiled()
    case = _case(extracted_result={**_case().extracted_result, "can_lift_15kg": False})

    result = score_extraction_accuracy(compiled, [case])

    field = next(f for f in result.fields if f.field == "can_lift_15kg")
    assert field.correct is False
    assert result.score < 100.0


def test_extraction_accuracy_flags_a_wrong_qualified_field() -> None:
    compiled = _compiled()
    case = _case(extracted_result={**_case().extracted_result, "qualified": False})

    result = score_extraction_accuracy(compiled, [case])

    field = next(f for f in result.fields if f.field == "qualified")
    assert field.correct is False


def test_extraction_accuracy_number_field_matches_within_tolerance() -> None:
    compiled = _compiled()
    case = _case(extracted_result={**_case().extracted_result, "years_experience": 2.0000001})

    result = score_extraction_accuracy(compiled, [case])

    assert next(f for f in result.fields if f.field == "years_experience").correct is True


def test_extraction_accuracy_free_text_uses_normalised_fuzzy_match() -> None:
    compiled = _compiled()
    case = _case(
        extracted_result={
            **_case().extracted_result,
            "availability": "  WEEKDAYS,   starting monday",
        }
    )

    result = score_extraction_accuracy(compiled, [case])

    assert next(f for f in result.fields if f.field == "availability").correct is True


def test_extraction_accuracy_free_text_rejects_an_unrelated_answer() -> None:
    compiled = _compiled()
    case = _case(extracted_result={**_case().extracted_result, "availability": "Not sure yet"})

    result = score_extraction_accuracy(compiled, [case])

    assert next(f for f in result.fields if f.field == "availability").correct is False


# ------------------------------------------------------------------------------------ efficiency


def test_efficiency_is_100_at_or_under_target() -> None:
    result = score_efficiency([_case(estimated_seconds=EFFICIENCY_TARGET_SECONDS)])
    assert result.score == 100.0
    assert result.cases[0].flagged is False


def test_efficiency_degrades_between_target_and_floor() -> None:
    result = score_efficiency([_case(estimated_seconds=135.0)])
    assert 0.0 < result.score < 100.0


def test_efficiency_flags_over_120_seconds() -> None:
    result = score_efficiency([_case(estimated_seconds=EFFICIENCY_FLAG_SECONDS + 1)])
    assert result.cases[0].flagged is True


def test_efficiency_does_not_flag_at_exactly_120_seconds() -> None:
    result = score_efficiency([_case(estimated_seconds=EFFICIENCY_FLAG_SECONDS)])
    assert result.cases[0].flagged is False


def test_efficiency_averages_across_cases() -> None:
    fast = _case(persona_id=uuid.uuid4(), estimated_seconds=60.0)
    slow = _case(persona_id=uuid.uuid4(), estimated_seconds=200.0)  # floored at 0

    result = score_efficiency([fast, slow])

    assert result.score == pytest.approx((100.0 + 0.0) / 2)


# --------------------------------------------------------------------------------------- coverage


async def test_coverage_makes_exactly_one_batched_call_for_all_personas(
    llm_settings: object,
) -> None:
    compiled = _compiled()
    cases = [_case(persona_id=uuid.uuid4()) for _ in range(3)]
    responses = {
        "_CoverageJudgeBatch": {
            "personas": [
                {
                    "archetype": case.archetype,
                    "asked": dict.fromkeys((q.id for q in compiled.screening_questions), True),
                }
                for case in cases
            ]
        }
    }
    service, provider = _service_with(responses, llm_settings)

    result = await score_coverage(compiled, cases, llm=service)

    assert len(provider.calls) == 1
    assert result.score == 100.0


async def test_coverage_never_sees_candidate_turns(llm_settings: object) -> None:
    compiled = _compiled()
    case = _case(
        transcript=[
            TranscriptTurn(speaker="agent", text="AGENT_MARKER_TEXT", turn=0),
            TranscriptTurn(speaker="candidate", text="CANDIDATE_MARKER_TEXT", turn=1),
        ]
    )
    responses = {
        "_CoverageJudgeBatch": {
            "personas": [
                {
                    "archetype": case.archetype,
                    "asked": dict.fromkeys((q.id for q in compiled.screening_questions), True),
                }
            ]
        }
    }
    service, provider = _service_with(responses, llm_settings)

    await score_coverage(compiled, [case], llm=service)

    prompt = provider.calls[0]["messages"][1]["content"]
    assert "AGENT_MARKER_TEXT" in prompt
    assert "CANDIDATE_MARKER_TEXT" not in prompt


async def test_coverage_raises_when_judge_drops_a_persona(llm_settings: object) -> None:
    compiled = _compiled()
    cases = [_case(archetype="QUALIFIED_EAGER"), _case(archetype="BUSY_HOSTILE")]
    responses = {
        "_CoverageJudgeBatch": {
            "personas": [
                {
                    "archetype": "QUALIFIED_EAGER",
                    "asked": dict.fromkeys((q.id for q in compiled.screening_questions), True),
                }
            ]
        }
    }
    service, _provider = _service_with(responses, llm_settings)

    with pytest.raises(ScoringError, match="BUSY_HOSTILE"):
        await score_coverage(compiled, cases, llm=service)


async def test_coverage_defaults_an_omitted_question_to_not_asked(llm_settings: object) -> None:
    compiled = _compiled()
    case = _case()
    responses = {
        "_CoverageJudgeBatch": {
            "personas": [{"archetype": case.archetype, "asked": {"can_lift_15kg": True}}]
        }
    }
    service, _provider = _service_with(responses, llm_settings)

    result = await score_coverage(compiled, [case], llm=service)

    asked = result.cases[0].asked
    assert asked["can_lift_15kg"] is True
    assert asked["availability"] is False


async def test_coverage_of_empty_cases_short_circuits_without_a_call(llm_settings: object) -> None:
    compiled = _compiled()
    service, _provider = _service_with({}, llm_settings)

    result = await score_coverage(compiled, [], llm=service)

    assert result.score == 100.0
    assert result.cases == []


# ----------------------------------------------------------------------------------- faithfulness


async def test_faithfulness_is_100_with_no_violations(llm_settings: object) -> None:
    compiled = _compiled()
    case = _case()
    responses = {
        "_FaithfulnessJudgeBatch": {"personas": [{"archetype": case.archetype, "violations": []}]}
    }
    service, _provider = _service_with(responses, llm_settings)

    result = await score_faithfulness(compiled, [case], llm=service)

    assert result.score == 100.0
    assert result.cases[0].violations == []


async def test_faithfulness_penalises_each_violation_and_keeps_the_quote(
    llm_settings: object,
) -> None:
    compiled = _compiled()
    case = _case()
    responses = {
        "_FaithfulnessJudgeBatch": {
            "personas": [
                {
                    "archetype": case.archetype,
                    "violations": [
                        {
                            "quote": "there's a Rs 2,000 joining bonus",
                            "reason": "not in approved facts",
                        }
                    ],
                }
            ]
        }
    }
    service, _provider = _service_with(responses, llm_settings)

    result = await score_faithfulness(compiled, [case], llm=service)

    assert result.score == 75.0
    assert result.cases[0].violations[0].quote == "there's a Rs 2,000 joining bonus"


async def test_faithfulness_raises_when_judge_drops_a_persona(llm_settings: object) -> None:
    compiled = _compiled()
    cases = [_case(archetype="QUALIFIED_EAGER"), _case(archetype="SALARY_FIRST")]
    responses = {
        "_FaithfulnessJudgeBatch": {
            "personas": [{"archetype": "QUALIFIED_EAGER", "violations": []}]
        }
    }
    service, _provider = _service_with(responses, llm_settings)

    with pytest.raises(ScoringError, match="SALARY_FIRST"):
        await score_faithfulness(compiled, cases, llm=service)


# -------------------------------------------------------------------------------------- composite


def test_composite_is_the_documented_weighted_average() -> None:
    compiled = _compiled()
    extraction = score_extraction_accuracy(compiled, [_case()])  # 100
    efficiency = score_efficiency([_case()])  # 100

    coverage = CoverageResult(score=80.0, cases=[CoverageCase(persona_id=uuid.uuid4(), asked={})])
    faithfulness = FaithfulnessResult(
        score=60.0, cases=[FaithfulnessCase(persona_id=uuid.uuid4(), score=60.0, violations=[])]
    )

    result = compute_composite(compiled, extraction, coverage, faithfulness, efficiency)

    assert result.composite == pytest.approx(100 * 0.40 + 80 * 0.25 + 60 * 0.25 + 100 * 0.10)


def test_failures_are_sorted_by_severity_then_metric_weight() -> None:
    compiled = _compiled()
    case_a = _case(persona_id=uuid.uuid4())
    case_b = _case(persona_id=uuid.uuid4())

    extraction = score_extraction_accuracy(
        compiled,
        [
            case_a.model_copy(
                update={"extracted_result": {**case_a.extracted_result, "qualified": False}}
            )
        ],
    )  # one CRITICAL failure (qualified) + no others
    coverage = CoverageResult(
        score=75.0,
        cases=[
            CoverageCase(
                persona_id=case_a.persona_id, asked={"availability": False, "can_lift_15kg": True}
            )
        ],
    )  # one MAJOR failure
    faithfulness = FaithfulnessResult(
        score=75.0,
        cases=[
            FaithfulnessCase(
                persona_id=case_a.persona_id,
                score=75.0,
                violations=[FaithfulnessViolation(quote="invented bonus", reason="not approved")],
            )
        ],
    )  # one CRITICAL failure
    efficiency = EfficiencyResult(
        score=90.0,
        cases=[
            EfficiencyCase(
                persona_id=case_b.persona_id,
                estimated_seconds=130.0,
                turn_count=10,
                score=90.0,
                flagged=True,
            )
        ],
    )  # one MINOR failure

    result = compute_composite(compiled, extraction, coverage, faithfulness, efficiency)

    severities = [f.severity for f in result.failures]
    assert severities == sorted(
        severities, key=lambda s: {"critical": 0, "major": 1, "minor": 2}[s]
    )
    # Both CRITICAL failures come first; extraction_accuracy (weight 40) sorts ahead of
    # faithfulness (weight 25) within that tier.
    assert result.failures[0].metric == "extraction_accuracy"
    assert result.failures[1].metric == "faithfulness"
    assert result.failures[2].metric == "coverage"
    assert result.failures[3].metric == "efficiency"


# ------------------------------------------------------------------------ the required scenario
#
# Hand-built transcript where the agent skips question 3 (availability) and invents a joining
# bonus. extraction_accuracy and efficiency are kept perfect on purpose so the drop is isolated
# to exactly the two metrics this scenario is about, and the expected weighted drop can be
# computed and asserted exactly rather than approximately.

_FABRICATED_BONUS_SENTENCE = (
    "there's also a Rs 2,000 joining bonus after your first month, on top of the pay"
)


def _skip_and_fabricate_case() -> CaseInput:
    transcript = [
        TranscriptTurn(
            speaker="agent",
            text="Hi Ravi, this is Neha calling about a Warehouse Associate role in Pune. "
            "Do you have ninety seconds to talk?",
            turn=0,
        ),
        TranscriptTurn(speaker="candidate", text="Sure, go ahead.", turn=1),
        TranscriptTurn(
            speaker="agent", text="Can you lift 15 kilos repeatedly through a shift?", turn=2
        ),
        TranscriptTurn(speaker="candidate", text="Yes, no problem.", turn=3),
        TranscriptTurn(speaker="agent", text="Do you have a valid government ID?", turn=4),
        TranscriptTurn(speaker="candidate", text="Yes, I have my Aadhaar card.", turn=5),
        TranscriptTurn(
            speaker="agent", text="How many years of warehouse experience do you have?", turn=6
        ),
        TranscriptTurn(speaker="candidate", text="About two years.", turn=7),
        # `availability` (question 3 of 4) is never asked. Instead the agent fabricates a fact.
        TranscriptTurn(
            speaker="agent",
            text=f"Great — one more thing, {_FABRICATED_BONUS_SENTENCE}. "
            "Thanks so much, we'll be in touch soon!",
            turn=8,
        ),
    ]
    ground_truth = {
        "can_lift_15kg": True,
        "has_id_proof": True,
        "availability": "Weekdays, starting Monday",
        "years_experience": 2.0,
        "interested": True,
        "qualified": True,
    }
    return CaseInput(
        persona_id=uuid.uuid4(),
        archetype="QUALIFIED_EAGER",
        ground_truth=ground_truth,
        off_script_questions=[],
        transcript=transcript,
        # Kept exactly equal to ground_truth (including `availability`, despite it never being
        # asked) so extraction_accuracy stays perfect — this scenario is about coverage and
        # faithfulness only, per the spec, not a third accidental extraction failure.
        extracted_result={k: v for k, v in ground_truth.items() if k != "interested"},
        estimated_seconds=45.0,  # well under the 90s target, so efficiency stays perfect too
        turn_count=len(transcript),
    )


async def test_skip_and_fabrication_scenario(llm_settings: object) -> None:
    compiled = _compiled()
    case = _skip_and_fabricate_case()

    responses = {
        "_CoverageJudgeBatch": {
            "personas": [
                {
                    "archetype": case.archetype,
                    "asked": {
                        "can_lift_15kg": True,
                        "has_id_proof": True,
                        "availability": False,
                        "years_experience": True,
                    },
                }
            ]
        },
        "_FaithfulnessJudgeBatch": {
            "personas": [
                {
                    "archetype": case.archetype,
                    "violations": [
                        {
                            "quote": _FABRICATED_BONUS_SENTENCE,
                            "reason": "joining bonus is not in the approved facts list",
                        }
                    ],
                }
            ]
        },
    }
    service, _provider = _service_with(responses, llm_settings)

    result = await score_rehearsal_run(compiled, [case], llm=service)

    # extraction_accuracy and efficiency are untouched.
    assert result.extraction_accuracy.score == 100.0
    assert result.efficiency.score == 100.0

    # Coverage catches the skip.
    assert result.coverage.score == 75.0  # 3 of 4 questions asked
    assert result.coverage.cases[0].asked["availability"] is False
    coverage_failures = [f for f in result.failures if f.metric == "coverage"]
    assert len(coverage_failures) == 1
    assert "Which days can you start?" in coverage_failures[0].description

    # Faithfulness catches the invention, with the quote.
    assert result.faithfulness.score == 75.0  # 100 - one violation * 25
    faithfulness_failures = [f for f in result.failures if f.metric == "faithfulness"]
    assert len(faithfulness_failures) == 1
    assert faithfulness_failures[0].transcript_excerpt == _FABRICATED_BONUS_SENTENCE
    assert faithfulness_failures[0].severity == "critical"

    # The composite drops by exactly the expected weighted amount: a 25-point coverage miss
    # weighted at 25%, plus a 25-point faithfulness miss weighted at 25% — nothing else moves.
    expected_drop = (100 - 75) * 0.25 + (100 - 75) * 0.25
    assert result.composite == pytest.approx(100 - expected_drop)
    assert result.composite == pytest.approx(87.5)
