"""Generate the six comparable candidate personas used to rehearse an agent version.

Every run scores against the same six archetypes so version-to-version comparisons stay apples
to apples (CLAUDE.md). The LLM only invents flavour: names, backstories, and the raw answer
values a persona would give for each screening question. `ground_truth.qualified` is computed
here in Python by applying the JD's knockout_criteria to those answers — never asked of the
model — which is what keeps scoring objective instead of a self-graded vibe check.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.persona import Persona
from app.schemas.compiled_jd import CompiledJD, KnockoutCriterion, ScreeningQuestion
from app.schemas.persona import ARCHETYPES, AnswerValue, Archetype, PersonaBatch
from app.services.llm import LLMService, get_llm_service

logger = structlog.get_logger()

# Archetypes whose ground_truth.qualified outcome is dictated by the spec. The other three
# (SALARY_FIRST, CODE_SWITCHER, BUSY_HOSTILE) are unconstrained here — their story just needs
# to be internally consistent, which evaluate_knockouts still enforces either way.
_EXPECTED_QUALIFIED: dict[Archetype, bool] = {
    "QUALIFIED_EAGER": True,
    "QUALIFIED_TERSE": True,
    "UNQUALIFIED_CLEAR": False,
}

_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, v: bool(a == v),
    "neq": lambda a, v: bool(a != v),
    "gte": lambda a, v: bool(a >= v),
    "lte": lambda a, v: bool(a <= v),
    "gt": lambda a, v: bool(a > v),
    "lt": lambda a, v: bool(a < v),
    "in": lambda a, v: bool(a in v),
    "not_in": lambda a, v: bool(a not in v),
}

_PERSONA_SYSTEM_PROMPT = """\
You invent candidate personas to rehearse a voice screening agent against, before it ever calls
a real person.

Generate EXACTLY these six archetypes, one persona each. Output MUST satisfy the provided JSON
schema exactly.

  QUALIFIED_EAGER    Meets every screening requirement. Cooperative, engaged, answers fully.
  QUALIFIED_TERSE    Meets every screening requirement. Answers in one or two words, volunteers
                     nothing extra.
  UNQUALIFIED_CLEAR  Fails exactly one screening requirement, unambiguously — no room to argue
                     the call either way.
  SALARY_FIRST       Meets every screening requirement. Only wants to talk about pay: deflects
                     every other question back to "what does it pay?" until that is actually
                     answered, then cooperates. This persona is the hardest test of whether the
                     agent stays inside facts_the_agent_may_state instead of inventing a number
                     to move the call along.
  CODE_SWITCHER      Meets every screening requirement. Starts the call in English and switches
                     to their local language partway through.
  BUSY_HOSTILE       Meets every screening requirement. Annoyed at being called, short-tempered,
                     wants off the phone quickly. Tests whether the agent can exit gracefully
                     without pushing.

For every persona, ground_truth_answers must give ONE value for EVERY screening question id
listed below, in the type that question's answer_type implies (true/false for boolean, a plain
number for number, one of the listed options verbatim for enum, free text otherwise). These
values are facts about the persona's story, not a judgement call — whether the persona is
disqualified is computed afterwards from what you put here, so make the answers actually match
the archetype:

  - QUALIFIED_EAGER, QUALIFIED_TERSE, SALARY_FIRST, CODE_SWITCHER, BUSY_HOSTILE: the answers
    must satisfy every knockout criterion listed below (none of them may fire).
  - UNQUALIFIED_CLEAR: the answers must fire exactly one knockout criterion, clearly — not a
    borderline or ambiguous case.

expected_interested is your call about whether this persona ends the call wanting to proceed —
it is flavour and is not graded.

Never invent a fact about the role beyond what is given below.
"""


class PersonaGenerationError(Exception):
    """The model's output was structurally valid but violated a hard rule of the persona spec."""


def evaluate_knockouts(criteria: list[KnockoutCriterion], answers: dict[str, AnswerValue]) -> bool:
    """True (qualified) iff no knockout criterion fires against these answers.

    Defensive on purpose: a criterion referencing a missing answer, or comparing incompatible
    types, is skipped rather than crashing. CompiledJD already guarantees every knockout
    references a real question id — this only guards a still-malformed answers dict.
    """
    for criterion in criteria:
        if criterion.question_id not in answers:
            continue
        operator = _OPERATORS[criterion.operator]
        try:
            fired = operator(answers[criterion.question_id], criterion.value)
        except TypeError:
            continue
        if fired:
            return False
    return True


def _answer_type_ok(question: ScreeningQuestion, value: AnswerValue) -> bool:
    if question.answer_type == "boolean":
        return isinstance(value, bool)
    if question.answer_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if question.answer_type == "enum":
        return isinstance(value, str) and value in (question.options or [])
    return isinstance(value, str)


def _invalid_answers(compiled: CompiledJD, answers: dict[str, AnswerValue]) -> list[str]:
    """Problems with one persona's ground_truth_answers: a missing question id, or a value
    that does not match that question's declared answer_type."""
    problems: list[str] = []
    for question in compiled.screening_questions:
        if question.id not in answers:
            problems.append(f"{question.id}: missing")
            continue
        value = answers[question.id]
        if not _answer_type_ok(question, value):
            problems.append(f"{question.id}: {value!r} is not a valid {question.answer_type}")
    return problems


def _render_questions(compiled: CompiledJD) -> str:
    lines = []
    for question in compiled.screening_questions:
        line = f"- {question.id} ({question.answer_type}): {question.text}"
        if question.options:
            line += f" [options: {', '.join(question.options)}]"
        lines.append(line)
    return "\n".join(lines)


def _render_knockouts(compiled: CompiledJD) -> str:
    if not compiled.knockout_criteria:
        return "(none — every answer combination qualifies)"
    return "\n".join(
        f"- {c.question_id} {c.operator} {c.value!r} disqualifies"
        for c in compiled.knockout_criteria
    )


def _user_prompt(compiled: CompiledJD) -> str:
    facts = "\n".join(f"- {fact}" for fact in compiled.facts_the_agent_may_state)
    locations = ", ".join(compiled.locations) or "an unspecified location"
    return f"""\
Role: {compiled.role_title} in {locations}

Screening questions:
{_render_questions(compiled)}

Knockout criteria:
{_render_knockouts(compiled)}

Facts you may draw on for background/situation flavour (do not contradict or go beyond them):
{facts}
"""


async def generate_personas(
    compiled: CompiledJD,
    *,
    job_id: Any = None,
    llm: LLMService | None = None,
) -> list[Persona]:
    """Generate the six comparable personas for a compiled JD.

    Not persisted — the caller decides whether to save them (see get_or_regenerate_personas).
    """
    service = llm or get_llm_service()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": _PERSONA_SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(compiled)},
    ]

    batch = await service.structured_complete("simulator", messages, PersonaBatch)
    try:
        return _personas_from_batch(compiled, batch, job_id=job_id)
    except PersonaGenerationError as first_error:
        logger.warning("persona_generation_invalid_retrying", error=str(first_error))

    # Retry ONCE, feeding back exactly what was wrong — same pattern as
    # LLMService.structured_complete's schema retry and propose_patch's dropped-question retry.
    # Needed because this is a domain-level check (a missing ground_truth_answers key, or a
    # persona's computed qualification not matching its archetype), which happens after the
    # model's JSON already validated against PersonaBatch's schema, so structured_complete's own
    # retry never sees it.
    repair_messages = [
        *messages,
        {"role": "assistant", "content": batch.model_dump_json()},
        {
            "role": "user",
            "content": (
                f"That output was invalid:\n{first_error}\n\n"
                "Return the full corrected set of six personas again, fixing only that problem."
            ),
        },
    ]
    batch = await service.structured_complete("simulator", repair_messages, PersonaBatch)
    return _personas_from_batch(compiled, batch, job_id=job_id)


def _personas_from_batch(
    compiled: CompiledJD, batch: PersonaBatch, *, job_id: Any
) -> list[Persona]:
    found = sorted(draft.archetype for draft in batch.personas)
    if found != sorted(ARCHETYPES):
        raise PersonaGenerationError(
            f"expected exactly the personas {sorted(ARCHETYPES)}, got {found}"
        )

    personas: list[Persona] = []
    for draft in batch.personas:
        problems = _invalid_answers(compiled, draft.ground_truth_answers)
        if problems:
            raise PersonaGenerationError(f"{draft.archetype}: {'; '.join(problems)}")

        qualified = evaluate_knockouts(compiled.knockout_criteria, draft.ground_truth_answers)
        expected = _EXPECTED_QUALIFIED.get(draft.archetype)
        if expected is not None and qualified is not expected:
            raise PersonaGenerationError(
                f"{draft.archetype} must be qualified={expected} given its answers, "
                f"computed qualified={qualified}"
            )

        ground_truth: dict[str, Any] = {
            **draft.ground_truth_answers,
            "interested": draft.expected_interested,
            "qualified": qualified,
        }
        personas.append(
            Persona(
                job_id=job_id,
                archetype=draft.archetype,
                profile=draft.profile.model_dump(mode="json"),
                ground_truth=ground_truth,
                behaviour=draft.behaviour.model_dump(mode="json"),
            )
        )
    return personas


async def get_or_regenerate_personas(
    session: AsyncSession,
    job_id: Any,
    compiled: CompiledJD,
    *,
    llm: LLMService | None = None,
    regenerate: bool = False,
) -> list[Persona]:
    """Personas persist per job so version-to-version comparisons are apples to apples.

    Returns the existing set unless `regenerate=True` is passed explicitly. Regenerating
    replaces the old personas and logs a warning: any rehearsal history scored against them is
    no longer comparable to runs against the new set.
    """
    existing = (
        (await session.execute(select(Persona).where(col(Persona.job_id) == job_id)))
        .scalars()
        .all()
    )

    if existing and not regenerate:
        return list(existing)

    if existing and regenerate:
        logger.warning(
            "personas_regenerated",
            job_id=str(job_id),
            previous_count=len(existing),
            note="rehearsal history for this job no longer compares against the new persona set",
        )
        for persona in existing:
            await session.delete(persona)
        await session.flush()

    personas = await generate_personas(compiled, job_id=job_id, llm=llm)
    session.add_all(personas)
    await session.flush()
    return personas
