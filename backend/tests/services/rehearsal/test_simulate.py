from __future__ import annotations

import json
import uuid
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
from app.services.rehearsal.simulate import (
    MAX_TURNS,
    run_rehearsal_cases,
    simulate_call,
)
from tests.services.conftest import FakeProvider
from tests.services.rehearsal.conftest import extraction_payload

CANDIDATE_DONE = "[[CALL_ENDED]]"
AGENT_DONE = "[[CALL_COMPLETE]]"


def service_with(responses: list[Any], settings: object) -> LLMService:
    nvidia = FakeProvider("nvidia", responses)
    return LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=settings,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- turn loop mechanics


async def test_first_turn_is_the_rendered_introduction_verbatim(
    agent_version: AgentVersion, persona: Persona, compiled: CompiledJD, llm_settings: object
) -> None:
    candidate_reply = f"Sure, go ahead. {CANDIDATE_DONE}"
    payload = extraction_payload(compiled, persona.ground_truth)
    service = service_with([candidate_reply, json.dumps(payload)], llm_settings)

    result = await simulate_call(agent_version, persona, compiled, llm=service)

    assert result.transcript[0].speaker == "agent"
    assert result.transcript[0].turn == 0
    # Placeholders substituted (custom_data from persona + compiled)...
    assert persona.profile["name"] in result.transcript[0].text
    assert compiled.role_title in result.transcript[0].text
    # ...and nothing else about the scripted line rewritten: it's introduction.format()'d, not
    # regenerated, so the rest of the literal text must survive untouched.
    assert "Do you have ninety seconds to talk?" in result.transcript[0].text
    assert "{callee_name}" not in result.transcript[0].text
    assert "{persona_name}" not in result.transcript[0].text


async def test_loop_stops_when_candidate_ends_the_call(
    agent_version: AgentVersion, persona: Persona, compiled: CompiledJD, llm_settings: object
) -> None:
    candidate_reply = f"Not interested, goodbye. {CANDIDATE_DONE}"
    payload = extraction_payload(compiled, persona.ground_truth, interested=False)
    service = service_with([candidate_reply, json.dumps(payload)], llm_settings)

    result = await simulate_call(agent_version, persona, compiled, llm=service)

    assert result.turn_count == 2
    assert len(result.transcript) == 2
    assert result.transcript[1].speaker == "candidate"
    assert CANDIDATE_DONE not in result.transcript[1].text


async def test_loop_stops_when_agent_concludes(
    agent_version: AgentVersion, persona: Persona, compiled: CompiledJD, llm_settings: object
) -> None:
    candidate_reply = "Yes, I have a two-wheeler and a licence."
    agent_reply = f"Great, that's everything — thank you, we'll be in touch. {AGENT_DONE}"
    payload = extraction_payload(compiled, persona.ground_truth)
    service = service_with([candidate_reply, agent_reply, json.dumps(payload)], llm_settings)

    result = await simulate_call(agent_version, persona, compiled, llm=service)

    assert result.turn_count == 3
    assert [t.speaker for t in result.transcript] == ["agent", "candidate", "agent"]
    assert AGENT_DONE not in result.transcript[2].text


async def test_loop_caps_at_max_turns_when_neither_side_ends_it(
    agent_version: AgentVersion, persona: Persona, compiled: CompiledJD, llm_settings: object
) -> None:
    # Turn 0 is the introduction (no LLM call); reaching MAX_TURNS needs MAX_TURNS - 1 more
    # LLM-generated turns, alternating candidate/agent, none of which ever emit a done token.
    filler = [f"Filler reply number {i}, still going." for i in range(MAX_TURNS - 1)]
    payload = extraction_payload(compiled, persona.ground_truth)
    service = service_with([*filler, json.dumps(payload)], llm_settings)

    result = await simulate_call(agent_version, persona, compiled, llm=service)

    assert result.turn_count == MAX_TURNS
    assert len(result.transcript) == MAX_TURNS


# ----------------------------------------------------------------------------------- custom_data


async def test_agent_turn_system_prompt_has_role_title_substituted_not_literal(
    agent_version: AgentVersion, persona: Persona, compiled: CompiledJD, llm_settings: object
) -> None:
    candidate_reply = "What shifts are available?"
    agent_reply = f"We have morning and evening shifts. {AGENT_DONE}"
    payload = extraction_payload(compiled, persona.ground_truth)
    nvidia = FakeProvider("nvidia", [candidate_reply, agent_reply, json.dumps(payload)])
    service = LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=llm_settings,  # type: ignore[arg-type]
    )

    await simulate_call(agent_version, persona, compiled, llm=service)

    agent_turn_call = nvidia.calls[1]
    system_prompt = agent_turn_call["messages"][0]["content"]
    assert compiled.role_title in system_prompt
    assert compiled.locations[0] in system_prompt
    assert "{role_title}" not in system_prompt
    assert "{role_location}" not in system_prompt


# -------------------------------------------------------------------------------- extraction step


async def test_extraction_uses_result_prompt_as_system_and_only_the_transcript(
    agent_version: AgentVersion, persona: Persona, compiled: CompiledJD, llm_settings: object
) -> None:
    candidate_reply = f"Sounds good. {CANDIDATE_DONE}"
    payload = extraction_payload(compiled, persona.ground_truth)
    nvidia = FakeProvider("nvidia", [candidate_reply, json.dumps(payload)])
    service = LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=llm_settings,  # type: ignore[arg-type]
    )

    result = await simulate_call(agent_version, persona, compiled, llm=service)

    extraction_call = nvidia.calls[-1]
    assert extraction_call["kind"] == "structured"
    assert extraction_call["messages"][0]["content"] == agent_version.result_prompt
    assert result.extracted_result["has_two_wheeler"] is True
    assert result.extracted_result["preferred_shift"] == "morning"


async def test_estimated_seconds_matches_the_documented_formula(
    agent_version: AgentVersion, persona: Persona, compiled: CompiledJD, llm_settings: object
) -> None:
    candidate_reply = f"Yes okay sure. {CANDIDATE_DONE}"  # 4 words
    payload = extraction_payload(compiled, persona.ground_truth)
    service = service_with([candidate_reply, json.dumps(payload)], llm_settings)

    result = await simulate_call(agent_version, persona, compiled, llm=service)

    total_words = sum(len(turn.text.split()) for turn in result.transcript)
    expected = total_words / 2.5 + (len(result.transcript) - 1) * 1.2
    assert result.estimated_seconds == expected


# ------------------------------------------------------------------------------ run_rehearsal_cases


async def _seed_run(
    db_session: AsyncSession, compiled: CompiledJD
) -> tuple[Job, AgentVersion, RehearsalRun]:
    job = Job(title="Delivery Rider", raw_jd="irrelevant")
    db_session.add(job)
    await db_session.flush()

    version = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    run = RehearsalRun(agent_version_id=version.id, status="RUNNING")
    db_session.add(run)
    await db_session.flush()
    return job, version, run


async def test_run_rehearsal_cases_persists_a_row_per_persona(
    db_session: AsyncSession,
    compiled: CompiledJD,
    persona: Persona,
    qualified_ground_truth: dict[str, Any],
    llm_settings: object,
) -> None:
    job, version, run = await _seed_run(db_session, compiled)
    persona.job_id = job.id
    second = Persona(
        id=uuid.uuid4(),
        job_id=job.id,
        archetype="QUALIFIED_TERSE",
        profile={**persona.profile, "name": "Second Candidate"},
        ground_truth=qualified_ground_truth,
        behaviour={**persona.behaviour, "verbosity": "terse"},
    )
    db_session.add_all([persona, second])
    await db_session.flush()

    payload = extraction_payload(compiled, qualified_ground_truth)
    done = f"Yes. {CANDIDATE_DONE}"
    # Both personas' candidate turns end immediately, so each needs exactly one dialogue
    # response plus one extraction response; six scripted responses cover both personas
    # regardless of which completes first under the concurrency semaphore.
    service = service_with([done, json.dumps(payload)] * 2, llm_settings)

    cases = await run_rehearsal_cases(
        db_session, run.id, version, compiled, [persona, second], llm=service
    )

    assert {c.persona_id for c in cases} == {persona.id, second.id}
    stored = (
        (await db_session.execute(select(RehearsalCase).where(col(RehearsalCase.run_id) == run.id)))
        .scalars()
        .all()
    )
    assert len(stored) == 2
    assert all(row.transcript is not None for row in stored)


async def test_run_rehearsal_cases_keeps_earlier_result_when_a_later_persona_fails(
    db_session: AsyncSession,
    compiled: CompiledJD,
    persona: Persona,
    qualified_ground_truth: dict[str, Any],
    llm_settings: object,
) -> None:
    job, version, run = await _seed_run(db_session, compiled)
    persona.job_id = job.id
    failing = Persona(
        id=uuid.uuid4(),
        job_id=job.id,
        archetype="BUSY_HOSTILE",
        profile={**persona.profile, "name": "UNIQUE_FAILING_CANDIDATE_MARKER"},
        ground_truth=qualified_ground_truth,
        behaviour={**persona.behaviour, "cooperativeness": "hostile"},
    )
    db_session.add_all([persona, failing])
    await db_session.flush()

    payload = extraction_payload(compiled, qualified_ground_truth)
    provider = _RaisesForMarkerProvider(
        marker="UNIQUE_FAILING_CANDIDATE_MARKER",
        ok_response=f"Yes. {CANDIDATE_DONE}",
        extraction_payload=payload,
    )
    service = LLMService(
        providers={"nvidia": provider},
        cache=InMemoryLLMCache(),
        settings=llm_settings,  # type: ignore[arg-type]
    )

    cases = await run_rehearsal_cases(
        db_session, run.id, version, compiled, [persona, failing], llm=service
    )

    assert len(cases) == 1
    assert cases[0].persona_id == persona.id
    stored = (
        (await db_session.execute(select(RehearsalCase).where(col(RehearsalCase.run_id) == run.id)))
        .scalars()
        .all()
    )
    assert len(stored) == 1
    assert stored[0].persona_id == persona.id


class _RaisesForMarkerProvider:
    """Fails deterministically for whichever persona's system prompt contains `marker`,
    regardless of task interleaving order under the concurrency semaphore — content-addressed
    rather than call-order-addressed, since two personas run concurrently and a shared FIFO
    queue (like FakeProvider) can't be scripted deterministically per-persona under that."""

    name = "nvidia"

    def __init__(
        self, *, marker: str, ok_response: str, extraction_payload: dict[str, Any]
    ) -> None:
        self.marker = marker
        self.ok_response = ok_response
        self.extraction_payload = extraction_payload

    async def complete(
        self, model: str, messages: list[dict[str, str]], temperature: float
    ) -> LLMResponse:
        joined = " ".join(m["content"] for m in messages)
        if self.marker in joined:
            raise RuntimeError("simulated persona failure")
        return LLMResponse(text=self.ok_response, model=model, provider=self.name)

    async def structured_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> LLMResponse:
        return LLMResponse(
            text=json.dumps(self.extraction_payload), model=model, provider=self.name
        )

    async def aclose(self) -> None:
        pass
