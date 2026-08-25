from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.integrations.llm.base import LLMResponse
from app.models.agent_version import AgentVersion
from app.models.enums import Language
from app.models.job import Job
from app.models.persona import Persona
from app.models.rehearsal import RehearsalCase, RehearsalRun
from app.schemas.compiled_jd import CompiledJD
from app.services.jd_compiler import create_initial_version
from app.services.llm import InMemoryLLMCache, LLMService
from app.services.rehearsal.run import run_rehearsal
from tests.services.rehearsal.conftest import extraction_payload

CANDIDATE_DONE = "[[CALL_ENDED]]"


class _RehearsalProvider:
    """Handles every call kind a full run_rehearsal makes: freeform dialogue (complete) plus
    three structured calls dispatched by schema_name — extraction always names its dynamic
    model "ExtractedResult" (see simulate.py's _build_result_model), while the two judges are
    named after their private schema classes in score.py. Content-addressed rather than
    order-addressed since personas run concurrently and coverage/faithfulness run concurrently
    with each other too."""

    name = "nvidia"

    def __init__(
        self,
        *,
        extraction: dict[str, Any],
        coverage: dict[str, Any],
        faithfulness: dict[str, Any],
        candidate_reply: str = f"All good, thanks. {CANDIDATE_DONE}",
        fail_marker: str | None = None,
    ) -> None:
        self.extraction = extraction
        self.coverage = coverage
        self.faithfulness = faithfulness
        self.candidate_reply = candidate_reply
        self.fail_marker = fail_marker
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, model: str, messages: list[dict[str, str]], temperature: float
    ) -> LLMResponse:
        self.calls.append({"kind": "complete"})
        if self.fail_marker and any(self.fail_marker in m["content"] for m in messages):
            raise RuntimeError("simulated persona failure")
        return LLMResponse(text=self.candidate_reply, model=model, provider=self.name)

    async def structured_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> LLMResponse:
        self.calls.append({"kind": "structured", "schema_name": schema_name})
        payload = {
            "_CoverageJudgeBatch": self.coverage,
            "_FaithfulnessJudgeBatch": self.faithfulness,
        }.get(schema_name, self.extraction)
        return LLMResponse(text=json.dumps(payload), model=model, provider=self.name)

    async def aclose(self) -> None:
        pass


def _service(provider: _RehearsalProvider, settings: object) -> LLMService:
    return LLMService(
        providers={"nvidia": provider},
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


def _clean_judgements(
    compiled: CompiledJD, archetype: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    coverage = {
        "personas": [
            {
                "archetype": archetype,
                "asked": dict.fromkeys((q.id for q in compiled.screening_questions), True),
            }
        ]
    }
    faithfulness = {"personas": [{"archetype": archetype, "violations": []}]}
    return coverage, faithfulness


async def test_run_rehearsal_persists_a_completed_run_with_scores(
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
    provider = _RehearsalProvider(
        extraction=extraction_payload(compiled, qualified_ground_truth),
        coverage=coverage,
        faithfulness=faithfulness,
    )
    service = _service(provider, llm_settings)

    run = await run_rehearsal(db_session, version, compiled, [persona], llm=service)

    assert run.status == "COMPLETED"
    assert run.finished_at is not None
    assert run.scores is not None
    assert run.scores["composite"] == 100.0
    # 1 dialogue turn + 1 extraction + 1 coverage (batched) + 1 faithfulness (batched).
    assert run.llm_calls == 4
    assert run.cached_calls == 0

    stored_cases = (
        (await db_session.execute(select(RehearsalCase).where(col(RehearsalCase.run_id) == run.id)))
        .scalars()
        .all()
    )
    assert len(stored_cases) == 1
    assert stored_cases[0].persona_id == persona.id
    assert stored_cases[0].failures == []
    assert stored_cases[0].metrics is not None
    assert stored_cases[0].metrics["coverage"]["asked"][compiled.screening_questions[0].id] is True


async def test_run_rehearsal_marks_failed_when_every_persona_simulation_fails(
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
    provider = _RehearsalProvider(
        extraction=extraction_payload(compiled, qualified_ground_truth),
        coverage=coverage,
        faithfulness=faithfulness,
        fail_marker=persona.profile["name"],
    )
    service = _service(provider, llm_settings)

    run = await run_rehearsal(db_session, version, compiled, [persona], llm=service)

    assert run.status == "FAILED"
    assert run.scores is None
    assert run.error is not None
    assert run.finished_at is not None


async def test_run_rehearsal_reuses_a_given_run_row_instead_of_creating_a_new_one(
    db_session: AsyncSession,
    compiled: CompiledJD,
    persona: Persona,
    qualified_ground_truth: dict[str, Any],
    llm_settings: object,
) -> None:
    """POST /versions/{id}/rehearse creates a PENDING row and hands its id back in the 202
    response before a background task ever calls run_rehearsal — that id must be the one that
    ends up COMPLETED, not a second, different row."""
    job, version = await _seed(db_session, compiled)
    persona.job_id = job.id
    db_session.add(persona)
    await db_session.flush()

    pending = RehearsalRun(agent_version_id=version.id, status="PENDING")
    db_session.add(pending)
    await db_session.flush()
    pending_id = pending.id

    coverage, faithfulness = _clean_judgements(compiled, persona.archetype)
    provider = _RehearsalProvider(
        extraction=extraction_payload(compiled, qualified_ground_truth),
        coverage=coverage,
        faithfulness=faithfulness,
    )
    service = _service(provider, llm_settings)

    run = await run_rehearsal(db_session, version, compiled, [persona], llm=service, run=pending)

    assert run.id == pending_id
    assert run.status == "COMPLETED"

    all_runs = (
        (
            await db_session.execute(
                select(RehearsalRun).where(col(RehearsalRun.agent_version_id) == version.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(all_runs) == 1  # never a second row created alongside the reused one
