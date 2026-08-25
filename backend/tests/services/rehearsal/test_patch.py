from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_version import AgentVersion
from app.models.enums import Language
from app.models.job import Job
from app.models.persona import Persona
from app.models.rehearsal import PromptPatch, RehearsalRun
from app.schemas.compiled_jd import CompiledJD
from app.services.jd_compiler import create_initial_version
from app.services.llm import InMemoryLLMCache, LLMService
from app.services.rehearsal.patch import (
    PatchProposalError,
    accept_patch,
    propose_patch,
    score_delta,
)
from tests.services.conftest import FakeProvider
from tests.services.rehearsal.conftest import extraction_payload
from tests.services.rehearsal.test_run import _clean_judgements, _RehearsalProvider

ADDITION = "REMEMBER: never invent a number that is not in the approved facts list."


def _compiler_service(responses: list[Any], settings: object) -> LLMService:
    nvidia = FakeProvider("nvidia", responses)
    return LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=settings,  # type: ignore[arg-type]
    )


async def _seed(db_session: AsyncSession, compiled: CompiledJD) -> tuple[Job, AgentVersion]:
    job = Job(title="Delivery Rider", raw_jd="irrelevant")
    db_session.add(job)
    await db_session.flush()
    version = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    await db_session.flush()
    return job, version


def _scores_with_failures(failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "composite": 80.0,
        "extraction_accuracy": {"score": 100.0, "fields": []},
        "coverage": {"score": 80.0, "cases": []},
        "faithfulness": {"score": 100.0, "cases": []},
        "efficiency": {"score": 100.0, "cases": []},
        "failures": failures,
    }


def _failure(metric: str, severity: str, description: str, excerpt: str = "") -> dict[str, Any]:
    return {
        "persona_id": str(uuid.uuid4()),
        "metric": metric,
        "severity": severity,
        "description": description,
        "transcript_excerpt": excerpt,
    }


def _patch_payload(revised_prompt: str, rationale: list[dict[str, Any]]) -> dict[str, Any]:
    return {"revised_agent_prompt": revised_prompt, "rationale": rationale}


# ------------------------------------------------------------------------------- propose_patch


async def test_propose_patch_raises_when_run_has_not_been_scored(
    db_session: AsyncSession, compiled: CompiledJD
) -> None:
    _, version = await _seed(db_session, compiled)
    run = RehearsalRun(agent_version_id=version.id, status="RUNNING", scores=None)
    db_session.add(run)
    await db_session.flush()

    with pytest.raises(PatchProposalError, match="not been scored"):
        await propose_patch(db_session, run, compiled)


async def test_propose_patch_persists_the_full_prompt_and_rationale(
    db_session: AsyncSession, compiled: CompiledJD, llm_settings: object
) -> None:
    _, version = await _seed(db_session, compiled)
    run = RehearsalRun(
        agent_version_id=version.id,
        status="COMPLETED",
        scores=_scores_with_failures(
            [_failure("faithfulness", "critical", "invented a joining bonus", "there's a bonus")]
        ),
    )
    db_session.add(run)
    await db_session.flush()

    revised = version.agent_prompt + "\n\n" + ADDITION
    payload = _patch_payload(
        revised,
        [
            {
                "failure_id": "1",
                "change_summary": "tightened fabrication rule",
                "quoted_new_text": ADDITION,
            }
        ],
    )
    service = _compiler_service([json.dumps(payload)], llm_settings)

    patch = await propose_patch(db_session, run, compiled, llm=service)

    assert patch.run_id == run.id
    assert patch.proposed_agent_prompt == revised
    assert patch.rationale == [
        {
            "failure_id": "1",
            "change_summary": "tightened fabrication rule",
            "quoted_new_text": ADDITION,
        }
    ]
    assert patch.accepted is False
    stored = await db_session.get(PromptPatch, patch.id)
    assert stored is not None


async def test_propose_patch_prompt_includes_only_the_top_six_failures(
    db_session: AsyncSession, compiled: CompiledJD, llm_settings: object
) -> None:
    _, version = await _seed(db_session, compiled)
    failures = [_failure("coverage", "major", f"never asked question {i}") for i in range(8)]
    run = RehearsalRun(
        agent_version_id=version.id, status="COMPLETED", scores=_scores_with_failures(failures)
    )
    db_session.add(run)
    await db_session.flush()

    revised = version.agent_prompt + "\n\n" + ADDITION
    payload = _patch_payload(revised, [])
    nvidia = FakeProvider("nvidia", [json.dumps(payload)])
    service = LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=llm_settings,  # type: ignore[arg-type]
    )

    await propose_patch(db_session, run, compiled, llm=service)

    user_prompt = nvidia.calls[0]["messages"][1]["content"]
    assert "never asked question 5" in user_prompt  # 0-indexed failure #6 (1-indexed "6.")
    assert "never asked question 6" not in user_prompt


async def test_propose_patch_retries_once_when_a_question_is_dropped(
    db_session: AsyncSession, compiled: CompiledJD, llm_settings: object
) -> None:
    _, version = await _seed(db_session, compiled)
    run = RehearsalRun(
        agent_version_id=version.id, status="COMPLETED", scores=_scores_with_failures([])
    )
    db_session.add(run)
    await db_session.flush()

    dropped_question = compiled.screening_questions[0].text
    bad_revision = version.agent_prompt.replace(dropped_question, "") + "\n\n" + ADDITION
    good_revision = version.agent_prompt + "\n\n" + ADDITION

    responses = [
        json.dumps(_patch_payload(bad_revision, [])),
        json.dumps(_patch_payload(good_revision, [])),
    ]
    nvidia = FakeProvider("nvidia", responses)
    service = LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=llm_settings,  # type: ignore[arg-type]
    )

    patch = await propose_patch(db_session, run, compiled, llm=service)

    assert patch.proposed_agent_prompt == good_revision
    assert len(nvidia.calls) == 2
    assert dropped_question in nvidia.calls[1]["messages"][-1]["content"]


async def test_propose_patch_raises_when_question_still_missing_after_retry(
    db_session: AsyncSession, compiled: CompiledJD, llm_settings: object
) -> None:
    _, version = await _seed(db_session, compiled)
    run = RehearsalRun(
        agent_version_id=version.id, status="COMPLETED", scores=_scores_with_failures([])
    )
    db_session.add(run)
    await db_session.flush()

    dropped_question = compiled.screening_questions[0].text
    bad_revision = version.agent_prompt.replace(dropped_question, "") + "\n\n" + ADDITION

    service = _compiler_service([json.dumps(_patch_payload(bad_revision, []))] * 2, llm_settings)

    with pytest.raises(PatchProposalError, match="still drops"):
        await propose_patch(db_session, run, compiled, llm=service)


async def test_propose_patch_rejects_a_prompt_that_looks_like_a_summary(
    db_session: AsyncSession, compiled: CompiledJD, llm_settings: object
) -> None:
    _, version = await _seed(db_session, compiled)
    run = RehearsalRun(
        agent_version_id=version.id, status="COMPLETED", scores=_scores_with_failures([])
    )
    db_session.add(run)
    await db_session.flush()

    too_short = "I tightened the fabrication warning and reworded the closing."
    service = _compiler_service([json.dumps(_patch_payload(too_short, []))], llm_settings)

    with pytest.raises(PatchProposalError, match="description of changes"):
        await propose_patch(db_session, run, compiled, llm=service)


async def test_propose_patch_rejects_a_rationale_quote_not_in_the_prompt(
    db_session: AsyncSession, compiled: CompiledJD, llm_settings: object
) -> None:
    _, version = await _seed(db_session, compiled)
    run = RehearsalRun(
        agent_version_id=version.id, status="COMPLETED", scores=_scores_with_failures([])
    )
    db_session.add(run)
    await db_session.flush()

    revised = version.agent_prompt + "\n\n" + ADDITION
    payload = _patch_payload(
        revised,
        [
            {
                "failure_id": "1",
                "change_summary": "x",
                "quoted_new_text": "this text is not in the prompt",
            }
        ],
    )
    service = _compiler_service([json.dumps(payload)], llm_settings)

    with pytest.raises(PatchProposalError, match="not found verbatim"):
        await propose_patch(db_session, run, compiled, llm=service)


# -------------------------------------------------------------------------------- accept_patch


async def test_accept_patch_creates_version_n_plus_1_and_reruns_the_same_personas(
    db_session: AsyncSession,
    compiled: CompiledJD,
    persona: Persona,
    qualified_ground_truth: dict[str, Any],
    llm_settings: object,
) -> None:
    job, version = await _seed(db_session, compiled)
    persona.job_id = job.id
    db_session.add(persona)
    await db_session.flush()

    coverage, faithfulness = _clean_judgements(compiled, persona.archetype)
    run_1_scores = _scores_with_failures([_failure("coverage", "major", "never asked something")])
    run_1 = RehearsalRun(agent_version_id=version.id, status="COMPLETED", scores=run_1_scores)
    db_session.add(run_1)
    await db_session.flush()

    revised_prompt = version.agent_prompt + "\n\n" + ADDITION
    patch = PromptPatch(
        run_id=run_1.id,
        proposed_agent_prompt=revised_prompt,
        rationale=[{"failure_id": "1", "change_summary": "x", "quoted_new_text": ADDITION}],
    )
    db_session.add(patch)
    await db_session.flush()

    rehearsal_provider = _RehearsalProvider(
        extraction=extraction_payload(compiled, qualified_ground_truth),
        coverage=coverage,
        faithfulness=faithfulness,
    )
    rehearsal_service = LLMService(
        providers={"nvidia": rehearsal_provider},
        cache=InMemoryLLMCache(),
        settings=llm_settings,  # type: ignore[arg-type]
    )

    accepted = await accept_patch(db_session, patch, compiled, llm=rehearsal_service)

    assert accepted.version.version_no == version.version_no + 1
    assert accepted.version.agent_prompt == revised_prompt
    assert accepted.version.job_id == job.id

    assert patch.accepted is True
    assert patch.resulting_version_id == accepted.version.id

    assert accepted.run.agent_version_id == accepted.version.id
    assert accepted.run.status == "COMPLETED"
    assert accepted.run.scores is not None
    assert accepted.run.scores["composite"] == 100.0


async def test_accept_patch_raises_when_the_parent_run_is_missing(
    db_session: AsyncSession, compiled: CompiledJD
) -> None:
    patch = PromptPatch(run_id=uuid.uuid4(), proposed_agent_prompt="whatever", rationale=[])
    # Not persisted (its run_id points nowhere) — accept_patch must fail before touching the DB.
    with pytest.raises(PatchProposalError, match="not found"):
        await accept_patch(db_session, patch, compiled)


# ---------------------------------------------------------------------------------- score_delta


def _run_with_scores(scores: dict[str, Any] | None) -> RehearsalRun:
    return RehearsalRun(agent_version_id=uuid.uuid4(), status="COMPLETED", scores=scores)


def test_score_delta_is_child_minus_parent_per_metric() -> None:
    parent = _run_with_scores(
        {
            "composite": 70.0,
            "extraction_accuracy": {"score": 90.0},
            "coverage": {"score": 60.0},
            "faithfulness": {"score": 75.0},
            "efficiency": {"score": 100.0},
        }
    )
    child = _run_with_scores(
        {
            "composite": 87.5,
            "extraction_accuracy": {"score": 100.0},
            "coverage": {"score": 80.0},
            "faithfulness": {"score": 100.0},
            "efficiency": {"score": 100.0},
        }
    )

    delta = score_delta(parent, child)

    assert delta["composite"] == pytest.approx(17.5)
    assert delta["extraction_accuracy"] == pytest.approx(10.0)
    assert delta["coverage"] == pytest.approx(20.0)
    assert delta["faithfulness"] == pytest.approx(25.0)
    assert delta["efficiency"] == pytest.approx(0.0)


def test_score_delta_is_negative_when_the_child_regresses() -> None:
    parent = _run_with_scores({"composite": 90.0})
    child = _run_with_scores({"composite": 60.0})

    assert score_delta(parent, child)["composite"] == pytest.approx(-30.0)


def test_score_delta_omits_metrics_missing_from_either_run() -> None:
    parent = _run_with_scores({"composite": 70.0})
    child = _run_with_scores(None)

    assert score_delta(parent, child) == {}


def test_score_delta_partial_when_only_some_components_present() -> None:
    parent = _run_with_scores({"composite": 70.0, "coverage": {"score": 60.0}})
    child = _run_with_scores({"composite": 80.0})

    delta = score_delta(parent, child)

    assert delta == {"composite": pytest.approx(10.0)}
