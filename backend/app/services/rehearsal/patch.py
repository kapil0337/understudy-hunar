"""Propose and accept a prompt patch: give the compiler role the current agent_prompt and the
run's worst failures, get back a revised prompt, and — once accepted — score it against the
same personas so the improvement (or regression) is measurable, not assumed.

propose_patch uses role="compiler" (not "simulator"): revising a prompt is a structured
authoring task like compiling a JD, not a call to roleplay.

Two constraints are validated after the call, not just stated in the prompt:
  * the revised prompt must actually be a full prompt, not a description of the diff — checked
    with a cheap length heuristic, the same style of backstop jd_compiler.py uses for
    document-dependent questions: it catches the obvious failure, it is not proof of compliance;
  * it must not have dropped a screening question — checked by requiring each original
    question's exact wording (as jd_compiler.py embeds it verbatim) to still appear in the
    revised prompt. This is retried ONCE, feeding back exactly which question(s) went missing.

"Do not add facts about the role" is stated in the prompt but not independently re-verified
here — that would mean re-running faithfulness judging on a prompt with no transcript yet to
judge, which is what the next rehearsal run (accept_patch) actually does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.agent_version import AgentVersion
from app.models.persona import Persona
from app.models.rehearsal import PromptPatch, RehearsalRun
from app.schemas.compiled_jd import CompiledJD, ScreeningQuestion
from app.services.jd_compiler import create_patched_version
from app.services.llm import LLMService, get_llm_service
from app.services.rehearsal.run import run_rehearsal

logger = structlog.get_logger()

TOP_FAILURES = 6
_MIN_REVISED_LENGTH_RATIO = 0.5

_DELTA_METRICS = ("composite", "extraction_accuracy", "coverage", "faithfulness", "efficiency")


class PatchProposalError(Exception):
    """The compiler's proposed patch was structurally valid but violated a hard rule."""


class _PatchRationaleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_id: str
    change_summary: str
    quoted_new_text: str


class _ProposedPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revised_agent_prompt: str = Field(min_length=1)
    rationale: list[_PatchRationaleItem] = Field(default_factory=list)


_PATCH_SYSTEM_PROMPT = """\
You revise a voice screening agent's prompt to fix problems a rehearsal run found, without
changing what the role actually is.

You will be given the agent's CURRENT prompt, its worst failures from the rehearsal (most
severe first, numbered), and the exhaustive list of facts it is allowed to state about the role.

Rules:

1. Return the FULL revised prompt, not a diff, not a summary, not a description of what you
   changed. The text you return REPLACES the current prompt verbatim — anything you leave out
   is gone.

2. Do not add any fact about the role beyond facts_the_agent_may_state. If a failure says the
   agent invented something, the fix is to make the prompt forbid that claim more clearly, not
   to make the claim official by adding it to the prompt.

3. Do not remove any screening question. Every question currently in the prompt's SCREENING
   QUESTIONS section must still appear, worded EXACTLY as it is now, character for character —
   you may freely rewrite everything else (framing, closing, the fabrication warning, tone) to
   address the failures.

4. For every change you make, add one rationale entry: {failure_id, change_summary,
   quoted_new_text}. failure_id is the number of the failure you are addressing, from the list
   below. quoted_new_text must be copied verbatim from the prompt you are returning — it is how
   your change gets checked, so it must actually appear in revised_agent_prompt.

Output MUST satisfy the provided JSON schema exactly.
"""


def _render_failures(failures: list[dict[str, Any]]) -> str:
    if not failures:
        return "(no failures recorded — this run scored cleanly)"
    lines = []
    for index, failure in enumerate(failures, start=1):
        excerpt = failure.get("transcript_excerpt")
        suffix = f" | excerpt: {excerpt!r}" if excerpt else ""
        lines.append(
            f"{index}. [{failure['severity']}] {failure['metric']}: {failure['description']}{suffix}"
        )
    return "\n".join(lines)


def _patch_user_prompt(
    agent_prompt: str, failures: list[dict[str, Any]], compiled: CompiledJD
) -> str:
    facts = "\n".join(f"- {fact}" for fact in compiled.facts_the_agent_may_state)
    return f"""\
CURRENT agent_prompt:
{agent_prompt}

Worst failures from the rehearsal (most severe first, numbered — use these numbers as \
failure_id):
{_render_failures(failures)}

facts_the_agent_may_state (the ONLY facts the agent may state about the role):
{facts}
"""


def _retry_prompt(missing: list[ScreeningQuestion]) -> str:
    lines = "\n".join(f"- {question.text}" for question in missing)
    return f"""\
That revised prompt dropped {len(missing)} screening question(s) — they no longer appear \
anywhere in it:
{lines}

Return the FULL corrected prompt again: restore every one of those questions worded exactly as \
above, while keeping the rest of your revision.
"""


def _dropped_questions(
    questions: list[ScreeningQuestion], revised_prompt: str
) -> list[ScreeningQuestion]:
    return [question for question in questions if question.text not in revised_prompt]


def _validate_full_prompt(original: str, revised: str) -> None:
    if len(revised) < len(original) * _MIN_REVISED_LENGTH_RATIO:
        raise PatchProposalError(
            "revised_agent_prompt looks like a description of changes, not the full prompt "
            f"({len(revised)} chars vs {len(original)} in the original)"
        )


def _validate_rationale_quotes(proposed: _ProposedPatch) -> None:
    missing = [
        item.failure_id
        for item in proposed.rationale
        if item.quoted_new_text not in proposed.revised_agent_prompt
    ]
    if missing:
        raise PatchProposalError(
            "rationale quoted_new_text was not found verbatim in the revised prompt for "
            f"failure_id(s): {missing}"
        )


async def propose_patch(
    session: AsyncSession,
    run: RehearsalRun,
    compiled: CompiledJD,
    *,
    llm: LLMService | None = None,
) -> PromptPatch:
    """Propose a revised agent_prompt addressing run's worst failures. Not accepted yet — the
    caller decides whether to keep it (see accept_patch)."""
    if run.scores is None:
        raise PatchProposalError(f"run {run.id} has not been scored yet — nothing to patch from")

    agent_version = await session.get(AgentVersion, run.agent_version_id)
    if agent_version is None:
        raise PatchProposalError(f"agent_version {run.agent_version_id} not found for run {run.id}")

    service = llm or get_llm_service()
    failures: list[dict[str, Any]] = run.scores.get("failures", [])[:TOP_FAILURES]
    questions = [ScreeningQuestion.model_validate(q) for q in agent_version.screening_questions]

    messages = [
        {"role": "system", "content": _PATCH_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _patch_user_prompt(agent_version.agent_prompt, failures, compiled),
        },
    ]
    proposed = await service.structured_complete("compiler", messages, _ProposedPatch)
    # Length first, before the dropped-question retry: a response that is obviously just a
    # summary is never worth spending a retry on to fix an unrelated missing-question complaint.
    _validate_full_prompt(agent_version.agent_prompt, proposed.revised_agent_prompt)

    missing = _dropped_questions(questions, proposed.revised_agent_prompt)
    if missing:
        logger.warning(
            "patch_dropped_questions_retrying",
            run_id=str(run.id),
            missing=[q.id for q in missing],
        )
        retry_messages = [
            *messages,
            {"role": "assistant", "content": proposed.model_dump_json()},
            {"role": "user", "content": _retry_prompt(missing)},
        ]
        proposed = await service.structured_complete("compiler", retry_messages, _ProposedPatch)
        _validate_full_prompt(agent_version.agent_prompt, proposed.revised_agent_prompt)
        missing = _dropped_questions(questions, proposed.revised_agent_prompt)
        if missing:
            raise PatchProposalError(
                "revised prompt still drops screening question(s) after one retry: "
                f"{[q.id for q in missing]}"
            )

    _validate_rationale_quotes(proposed)

    patch = PromptPatch(
        run_id=run.id,
        proposed_agent_prompt=proposed.revised_agent_prompt,
        rationale=[item.model_dump(mode="json") for item in proposed.rationale],
    )
    session.add(patch)
    await session.flush()
    return patch


@dataclass
class AcceptedPatch:
    version: AgentVersion
    run: RehearsalRun


async def _personas_for_job(session: AsyncSession, job_id: uuid.UUID) -> list[Persona]:
    rows = await session.execute(select(Persona).where(col(Persona.job_id) == job_id))
    return list(rows.scalars().all())


async def accept_patch(
    session: AsyncSession,
    patch: PromptPatch,
    compiled: CompiledJD,
    *,
    llm: LLMService | None = None,
) -> AcceptedPatch:
    """Accept patch: create version n+1 (origin=PATCHED) from its proposed_agent_prompt, then
    immediately rehearse that new version against the same personas the parent run used — a
    patch's effect is measured, never assumed."""
    base_run = await session.get(RehearsalRun, patch.run_id)
    if base_run is None:
        raise PatchProposalError(f"rehearsal_run {patch.run_id} not found for patch {patch.id}")

    base_version = await session.get(AgentVersion, base_run.agent_version_id)
    if base_version is None:
        raise PatchProposalError(f"agent_version {base_run.agent_version_id} not found")

    new_version = await create_patched_version(session, base_version, patch.proposed_agent_prompt)

    patch.accepted = True
    patch.resulting_version_id = new_version.id
    session.add(patch)
    await session.flush()

    # Personas persist per job (app/services/personas.py) rather than per run, so "the same
    # personas" the parent run used is simply every persona on this job.
    personas = await _personas_for_job(session, base_version.job_id)
    new_run = await run_rehearsal(session, new_version, compiled, personas, llm=llm)

    return AcceptedPatch(version=new_version, run=new_run)


def _metric_score(scores: dict[str, Any], metric: str) -> float | None:
    if metric == "composite":
        value = scores.get("composite")
        return float(value) if isinstance(value, int | float) else None
    component = scores.get(metric)
    if not isinstance(component, dict):
        return None
    value = component.get("score")
    return float(value) if isinstance(value, int | float) else None


def score_delta(parent_run: RehearsalRun, child_run: RehearsalRun) -> dict[str, float]:
    """Per-metric score delta (child minus parent), composite included. Positive means the
    child scored higher. A metric is omitted if either run lacks scores for it (e.g. a run that
    failed outright)."""
    parent_scores = parent_run.scores or {}
    child_scores = child_run.scores or {}

    delta: dict[str, float] = {}
    for metric in _DELTA_METRICS:
        parent_value = _metric_score(parent_scores, metric)
        child_value = _metric_score(child_scores, metric)
        if parent_value is None or child_value is None:
            continue
        delta[metric] = child_value - parent_value
    return delta
