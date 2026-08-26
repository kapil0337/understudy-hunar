"""Score a rehearsal run: four independent metrics, combined into one composite that is never
shown without its breakdown.

Two metrics are deterministic and need no model call:
  * extraction_accuracy — extracted_result vs persona.ground_truth, field by field.
  * efficiency          — estimated_seconds/turn_count against a 90s target.

Two are judged, and each runs EXACTLY ONCE per run, scoring all personas in a single batched
call — never once per persona. That is a cost property (six separate judge calls would be six
times the tokens for the same verdict) and a consistency one (one call means one read of the
approved-facts list and one standard applied to every persona, rather than the judge's mood
drifting call to call):
  * coverage      — fed the question list and the agent's own turns only (never the candidate's
                    answers, so it is scored on what was asked, not what was answered).
  * faithfulness  — fed the approved facts and the agent's own turns; flags any claim outside
                    that list, or an off-script question answered instead of deferred, with the
                    offending quote.

composite = extraction_accuracy*0.40 + coverage*0.25 + faithfulness*0.25 + efficiency*0.10.
compute_composite() is the ONLY place that number is produced, and it always returns it bundled
with all four components and the failures list — a bare composite is exactly the opaque number
this product exists to replace (CLAUDE.md), so nothing in this module hands one back alone.
"""

from __future__ import annotations

import asyncio
import difflib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.schemas.compiled_jd import CompiledJD
from app.schemas.rehearsal import (
    CaseInput,
    CoverageCase,
    CoverageResult,
    EfficiencyCase,
    EfficiencyResult,
    ExtractionAccuracyResult,
    Failure,
    FaithfulnessCase,
    FaithfulnessResult,
    FaithfulnessViolation,
    FieldAccuracy,
    Metric,
    RehearsalScore,
    Severity,
)
from app.services.llm import LLMService, get_llm_service

_WEIGHTS: dict[Metric, float] = {
    "extraction_accuracy": 40.0,
    "coverage": 25.0,
    "faithfulness": 25.0,
    "efficiency": 10.0,
}
_SEVERITY_RANK: dict[Severity, int] = {"critical": 0, "major": 1, "minor": 2}


class ScoringError(Exception):
    """A judge's output was structurally valid but did not cover every persona being scored."""


# ---------------------------------------------------------------- extraction_accuracy (deterministic)

_FUZZY_MATCH_THRESHOLD = 0.6


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _free_text_matches(expected: str, actual: str) -> bool:
    ratio = difflib.SequenceMatcher(None, _normalise(expected), _normalise(actual)).ratio()
    return ratio >= _FUZZY_MATCH_THRESHOLD


def _field_matches(answer_type: str, expected: Any, actual: Any) -> bool:
    if answer_type == "boolean":
        return isinstance(actual, bool) and actual == expected
    if answer_type == "number":
        # isinstance(True, int) is True in Python, so bools are excluded explicitly rather
        # than treated as 0/1 numbers.
        if isinstance(actual, bool) or not isinstance(actual, int | float):
            return False
        if isinstance(expected, bool) or not isinstance(expected, int | float):
            return False
        return abs(float(actual) - float(expected)) < 1e-6
    if answer_type == "enum":
        return isinstance(actual, str) and actual == expected
    if answer_type == "free_text":
        return (
            isinstance(actual, str)
            and isinstance(expected, str)
            and _free_text_matches(expected, actual)
        )
    return bool(actual == expected)


def score_extraction_accuracy(
    compiled: CompiledJD, cases: list[CaseInput]
) -> ExtractionAccuracyResult:
    """Per screening question plus `qualified`, exact match for boolean/number/enum, normalised
    fuzzy match for free_text. Reports every field, not just an aggregate."""
    fields: list[FieldAccuracy] = []

    for case in cases:
        for question in compiled.screening_questions:
            expected = case.ground_truth.get(question.id)
            actual = case.extracted_result.get(question.id)
            fields.append(
                FieldAccuracy(
                    persona_id=case.persona_id,
                    field=question.id,
                    expected=expected,
                    actual=actual,
                    correct=_field_matches(question.answer_type, expected, actual),
                )
            )

        expected_qualified = case.ground_truth.get("qualified")
        actual_qualified = case.extracted_result.get("qualified")
        fields.append(
            FieldAccuracy(
                persona_id=case.persona_id,
                field="qualified",
                expected=expected_qualified,
                actual=actual_qualified,
                correct=isinstance(actual_qualified, bool)
                and actual_qualified == expected_qualified,
            )
        )

    correct = sum(1 for field in fields if field.correct)
    score = (correct / len(fields) * 100) if fields else 100.0
    return ExtractionAccuracyResult(score=score, fields=fields)


# ------------------------------------------------------------------------ efficiency (deterministic)

EFFICIENCY_TARGET_SECONDS = 90.0
EFFICIENCY_FLAG_SECONDS = 120.0
_EFFICIENCY_FLOOR_SECONDS = 180.0  # score reaches 0 here; linear between target and floor


def _case_efficiency_score(estimated_seconds: float) -> float:
    if estimated_seconds <= EFFICIENCY_TARGET_SECONDS:
        return 100.0
    if estimated_seconds >= _EFFICIENCY_FLOOR_SECONDS:
        return 0.0
    span = _EFFICIENCY_FLOOR_SECONDS - EFFICIENCY_TARGET_SECONDS
    return 100.0 * (1 - (estimated_seconds - EFFICIENCY_TARGET_SECONDS) / span)


def score_efficiency(cases: list[CaseInput]) -> EfficiencyResult:
    """estimated_seconds (and turn_count, carried through for context) against a 90s target;
    flagged whenever a case runs over 120s."""
    case_results = [
        EfficiencyCase(
            persona_id=case.persona_id,
            estimated_seconds=case.estimated_seconds,
            turn_count=case.turn_count,
            score=_case_efficiency_score(case.estimated_seconds),
            flagged=case.estimated_seconds > EFFICIENCY_FLAG_SECONDS,
        )
        for case in cases
    ]
    score = sum(c.score for c in case_results) / len(case_results) if case_results else 100.0
    return EfficiencyResult(score=score, cases=case_results)


# --------------------------------------------------------------------------------- coverage (judged)


def _build_coverage_batch_model(question_ids: list[str]) -> type[BaseModel]:
    """A fresh judge-response model per compiled JD: `asked` becomes one REQUIRED boolean field
    per screening question id, not the open dict[str, bool] shape a provider enforcing strict
    structured output (e.g. Groq) rejects outright — additionalProperties:false can only be
    expressed for a fixed set of properties, never for a deliberately open map. Same fix, and
    same underlying reason, as app/services/personas.py's _build_persona_batch_model.

    Named to match the original static classes' __name__ (leading underscore and all): the
    LLM cache key and every FakeProvider in this package's tests dispatch on schema_name, which
    is response_model.__name__ — a differently-named dynamic model would silently stop matching
    both.
    """
    asked_fields = {qid: (bool, ...) for qid in question_ids}
    asked_model = create_model(
        "_CoverageAsked", __config__=ConfigDict(extra="forbid"), **asked_fields
    )
    persona_model = create_model(
        "_CoverageJudgePersona",
        __config__=ConfigDict(extra="forbid"),
        archetype=(str, ...),
        asked=(asked_model, ...),
    )
    return create_model(
        "_CoverageJudgeBatch",
        __config__=ConfigDict(extra="forbid"),
        personas=(list[persona_model], ...),
    )


_COVERAGE_SYSTEM_PROMPT = """\
You are auditing a recruiter's phone screening call against its required question list.

You will be given the required screening questions and, for several candidates identified by
archetype, ONLY the recruiter's own turns from that call — the candidate's answers are withheld
on purpose, because you are checking what was ASKED, not what was answered.

For every persona and every question id, decide whether the recruiter actually asked that
question at some point, in substance — a rewording counts, a question never raised in any form
does not. Return one boolean per question id per persona, for every persona and every question
listed. Output MUST satisfy the provided JSON schema exactly.
"""


def _agent_turns(case: CaseInput) -> str:
    return "\n".join(f"- {turn.text}" for turn in case.transcript if turn.speaker == "agent")


def _coverage_user_prompt(compiled: CompiledJD, cases: list[CaseInput]) -> str:
    questions = "\n".join(f"- {q.id}: {q.text}" for q in compiled.screening_questions)
    personas = "\n\n".join(
        f"Persona: {case.archetype}\nRecruiter turns:\n{_agent_turns(case)}" for case in cases
    )
    return f"Required screening questions:\n{questions}\n\n{personas}"


async def score_coverage(
    compiled: CompiledJD, cases: list[CaseInput], *, llm: LLMService | None = None
) -> CoverageResult:
    if not cases:
        return CoverageResult(score=100.0, cases=[])

    service = llm or get_llm_service()
    question_ids = [q.id for q in compiled.screening_questions]
    batch = await service.structured_complete(
        "simulator",
        [
            {"role": "system", "content": _COVERAGE_SYSTEM_PROMPT},
            {"role": "user", "content": _coverage_user_prompt(compiled, cases)},
        ],
        _build_coverage_batch_model(question_ids),
    )
    by_archetype = {persona.archetype: persona.asked.model_dump() for persona in batch.personas}
    _require_full_coverage(cases, set(by_archetype), "coverage")

    case_results: list[CoverageCase] = []
    correct = 0
    total = 0
    for case in cases:
        asked = by_archetype[case.archetype]
        # A question id the judge omitted for a persona it DID cover defaults to "not asked" —
        # the same fail-safe direction as a covered persona missing entirely (see
        # _require_full_coverage): coverage would rather over-flag than silently pass a skip.
        normalised = {qid: bool(asked.get(qid, False)) for qid in question_ids}
        case_results.append(CoverageCase(persona_id=case.persona_id, asked=normalised))
        correct += sum(1 for was_asked in normalised.values() if was_asked)
        total += len(normalised)

    score = (correct / total * 100) if total else 100.0
    return CoverageResult(score=score, cases=case_results)


# ----------------------------------------------------------------------------- faithfulness (judged)


class _FaithfulnessJudgeViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str
    reason: str


class _FaithfulnessJudgePersona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archetype: str
    violations: list[_FaithfulnessJudgeViolation] = Field(default_factory=list)


class _FaithfulnessJudgeBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personas: list[_FaithfulnessJudgePersona]


_FAITHFULNESS_SYSTEM_PROMPT = """\
You are auditing a recruiter's phone screening call for faithfulness to an approved fact list.

You will be given the exhaustive list of facts the recruiter is allowed to state about the
role and, for several candidates identified by archetype, that candidate's off-script questions
plus ONLY the recruiter's own turns from the call.

Flag a violation whenever the recruiter, in its own turns:
  - states ANY claim about the role (pay, shift, benefits, location, requirements, timelines,
    anything) that is not covered by the approved fact list, even if it sounds plausible or
    generous — an invented number or benefit is exactly the failure this is checking for; or
  - directly answers an off-script question instead of saying it does not have that detail and
    a human recruiter will follow up.

For each violation, quote the offending sentence VERBATIM from the recruiter's turn, plus a
short reason. A recruiter that only uses the approved facts and defers everything else gets an
empty violations list — include every persona given to you, even ones with no violations.
Output MUST satisfy the provided JSON schema exactly.
"""

_VIOLATION_PENALTY = 25.0


def _faithfulness_user_prompt(compiled: CompiledJD, cases: list[CaseInput]) -> str:
    facts = "\n".join(f"- {fact}" for fact in compiled.facts_the_agent_may_state)
    personas = "\n\n".join(
        f"Persona: {case.archetype}\n"
        f"Off-script questions this candidate might ask: "
        f"{', '.join(case.off_script_questions) or '(none)'}\n"
        f"Recruiter turns:\n{_agent_turns(case)}"
        for case in cases
    )
    return f"Approved facts:\n{facts}\n\n{personas}"


async def score_faithfulness(
    compiled: CompiledJD, cases: list[CaseInput], *, llm: LLMService | None = None
) -> FaithfulnessResult:
    if not cases:
        return FaithfulnessResult(score=100.0, cases=[])

    service = llm or get_llm_service()
    batch = await service.structured_complete(
        "simulator",
        [
            {"role": "system", "content": _FAITHFULNESS_SYSTEM_PROMPT},
            {"role": "user", "content": _faithfulness_user_prompt(compiled, cases)},
        ],
        _FaithfulnessJudgeBatch,
    )
    by_archetype = {persona.archetype: persona.violations for persona in batch.personas}
    _require_full_coverage(cases, set(by_archetype), "faithfulness")

    case_results: list[FaithfulnessCase] = []
    for case in cases:
        violations = [
            FaithfulnessViolation(quote=v.quote, reason=v.reason)
            for v in by_archetype[case.archetype]
        ]
        score = max(0.0, 100.0 - _VIOLATION_PENALTY * len(violations))
        case_results.append(
            FaithfulnessCase(persona_id=case.persona_id, score=score, violations=violations)
        )

    score = sum(c.score for c in case_results) / len(case_results)
    return FaithfulnessResult(score=score, cases=case_results)


def _require_full_coverage(
    cases: list[CaseInput], judged_archetypes: set[str], judge_name: str
) -> None:
    """Fail loudly rather than silently defaulting either direction when a judge drops a
    persona entirely — the wrong default is a real risk here (missing => "no violations found"
    would quietly hide the exact fabrication this metric exists to catch)."""
    missing = {case.archetype for case in cases} - judged_archetypes
    if missing:
        raise ScoringError(f"{judge_name} judgement is missing persona(s): {sorted(missing)}")


# ---------------------------------------------------------------------------------- composite


def _extraction_failures(result: ExtractionAccuracyResult) -> list[Failure]:
    failures = []
    for field in result.fields:
        if field.correct:
            continue
        severity: Severity = "critical" if field.field == "qualified" else "major"
        failures.append(
            Failure(
                persona_id=field.persona_id,
                metric="extraction_accuracy",
                severity=severity,
                description=f"{field.field}: expected {field.expected!r}, extracted {field.actual!r}",
                transcript_excerpt="",
            )
        )
    return failures


def _coverage_failures(compiled: CompiledJD, result: CoverageResult) -> list[Failure]:
    question_text = {q.id: q.text for q in compiled.screening_questions}
    failures = []
    for case in result.cases:
        for question_id, asked in case.asked.items():
            if asked:
                continue
            failures.append(
                Failure(
                    persona_id=case.persona_id,
                    metric="coverage",
                    severity="major",
                    description=f"never asked: {question_text.get(question_id, question_id)}",
                    transcript_excerpt="",
                )
            )
    return failures


def _faithfulness_failures(result: FaithfulnessResult) -> list[Failure]:
    failures = []
    for case in result.cases:
        for violation in case.violations:
            failures.append(
                Failure(
                    persona_id=case.persona_id,
                    metric="faithfulness",
                    severity="critical",
                    description=violation.reason,
                    transcript_excerpt=violation.quote,
                )
            )
    return failures


def _efficiency_failures(result: EfficiencyResult) -> list[Failure]:
    failures = []
    for case in result.cases:
        if not case.flagged:
            continue
        failures.append(
            Failure(
                persona_id=case.persona_id,
                metric="efficiency",
                severity="minor",
                description=(
                    f"estimated {case.estimated_seconds:.0f}s over the "
                    f"{int(EFFICIENCY_FLAG_SECONDS)}s flag threshold, in {case.turn_count} turns"
                ),
                transcript_excerpt="",
            )
        )
    return failures


def compute_composite(
    compiled: CompiledJD,
    extraction_accuracy: ExtractionAccuracyResult,
    coverage: CoverageResult,
    faithfulness: FaithfulnessResult,
    efficiency: EfficiencyResult,
) -> RehearsalScore:
    """Combine four already-scored components into the composite. The ONLY place that number is
    computed — see the module docstring for why it is never returned without this breakdown."""
    composite = (
        extraction_accuracy.score * _WEIGHTS["extraction_accuracy"]
        + coverage.score * _WEIGHTS["coverage"]
        + faithfulness.score * _WEIGHTS["faithfulness"]
        + efficiency.score * _WEIGHTS["efficiency"]
    ) / 100.0

    failures = [
        *_extraction_failures(extraction_accuracy),
        *_coverage_failures(compiled, coverage),
        *_faithfulness_failures(faithfulness),
        *_efficiency_failures(efficiency),
    ]
    # Severity first, then metric weight (both descending) — ties (coverage vs faithfulness,
    # equally weighted) keep the collection order above, extraction_accuracy-first.
    failures.sort(key=lambda f: (_SEVERITY_RANK[f.severity], -_WEIGHTS[f.metric]))

    return RehearsalScore(
        composite=composite,
        extraction_accuracy=extraction_accuracy,
        coverage=coverage,
        faithfulness=faithfulness,
        efficiency=efficiency,
        failures=failures,
    )


async def score_rehearsal_run(
    compiled: CompiledJD, cases: list[CaseInput], *, llm: LLMService | None = None
) -> RehearsalScore:
    """Score a full rehearsal run: both judged metrics run once each, concurrently, then every
    component is combined by compute_composite."""
    service = llm or get_llm_service()

    extraction_accuracy = score_extraction_accuracy(compiled, cases)
    efficiency = score_efficiency(cases)
    coverage, faithfulness = await asyncio.gather(
        score_coverage(compiled, cases, llm=service),
        score_faithfulness(compiled, cases, llm=service),
    )

    return compute_composite(compiled, extraction_accuracy, coverage, faithfulness, efficiency)
