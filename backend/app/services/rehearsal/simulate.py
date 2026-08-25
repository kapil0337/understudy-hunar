"""Simulate one rehearsal call between the actual agent prompt and a candidate persona.

Two actors, both driven through app/services/llm.py with role="simulator" (CLAUDE.md — every
LLM call goes through llm.py, and there is no third role for "the agent side of a rehearsal";
rehearsing IS simulating a call, on both sides of it):

  * The agent side uses agent_version.agent_prompt and .introduction VERBATIM as its system
    prompt, with only the documented {persona_name}/{callee_name}/{role_title}/{role_location}
    placeholders substituted — the same substitution Hunar performs from custom_data at call
    time. Nothing else about the prompt is paraphrased, reworded, or "improved": the whole
    point of a rehearsal is to test the exact prompt Hunar will receive.
  * The candidate side is built from the persona's profile, behaviour, and ground_truth, and is
    instructed to stay in character, stay consistent with ground_truth, and never volunteer
    unasked information — so a coverage/faithfulness failure is the agent's, not a leak.

The agent's `introduction` is spoken verbatim as turn 0 rather than generated, since that field
IS the literal scripted opening line Hunar has the agent speak — there's nothing to simulate
there, only to render.

Extraction happens in a separate, later call against result_prompt/result_schema and the
finished transcript ONLY — mirroring Hunar's own server-side extraction. The agent is never
asked to report its own results.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_version import AgentVersion
from app.models.persona import Persona
from app.models.rehearsal import RehearsalCase
from app.schemas.compiled_jd import CompiledJD
from app.schemas.rehearsal import SimulatedCall, TranscriptTurn
from app.services.llm import LLMService, get_llm_service

logger = structlog.get_logger()

MAX_TURNS = 12
_WORDS_PER_SECOND = 2.5
_SECONDS_PER_TURN_BOUNDARY = 1.2

_AGENT_DONE_TOKEN = "[[CALL_COMPLETE]]"
_CANDIDATE_DONE_TOKEN = "[[CALL_ENDED]]"

# The four placeholders Hunar substitutes from the agent's own persona_name plus custom_data
# (see CLAUDE.md and app/services/jd_compiler.py's build_agent_prompt/build_introduction).
_PLACEHOLDER_KEYS = ("persona_name", "callee_name", "role_title", "role_location")


def _render(template: str, values: dict[str, str]) -> str:
    """Substitute only the documented placeholders, by plain replace rather than str.format —
    a PATCHED agent_prompt is free-form LLM output and may contain unrelated `{...}` text that
    .format() would choke on."""
    rendered = template
    for key in _PLACEHOLDER_KEYS:
        if key in values:
            rendered = rendered.replace("{" + key + "}", values[key])
    return rendered


def _custom_data(
    agent_version: AgentVersion, persona: Persona, compiled: CompiledJD
) -> dict[str, str]:
    location = compiled.locations[0] if compiled.locations else "the listed location"
    return {
        "persona_name": agent_version.persona_name,
        "callee_name": str(persona.profile.get("name", "the candidate")),
        "role_title": compiled.role_title,
        "role_location": location,
    }


def _agent_system_prompt(agent_prompt: str) -> str:
    return (
        f"{agent_prompt}\n\n"
        "When you have delivered your closing and the call is completely finished, end your "
        f"final message with the exact token {_AGENT_DONE_TOKEN} and say nothing after it."
    )


def _candidate_system_prompt(persona: Persona, compiled: CompiledJD) -> str:
    profile = persona.profile
    behaviour = persona.behaviour
    ground_truth = persona.ground_truth

    question_by_id = {q.id: q.text for q in compiled.screening_questions}
    facts_lines = [
        f"- {question_by_id.get(qid, qid)} -> {value}"
        for qid, value in ground_truth.items()
        if qid in question_by_id
    ]
    interest_line = (
        "Overall you ARE interested in this role, and that should come through naturally over "
        "the call."
        if ground_truth.get("interested")
        else "Overall you are NOT particularly interested in this role — you may go through "
        "with the screening anyway, but you are not sold on it."
    )

    language_line = (
        f"You start the call speaking English. After a couple of exchanges, start mixing in "
        f"phrases or full sentences in {profile.get('language', 'your local language')} the way "
        "a natural code-switcher would, while staying understandable."
        if behaviour.get("language_switching")
        else "Speak only English throughout."
    )

    off_script = behaviour.get("off_script_questions") or []
    off_script_line = (
        f"At a natural moment in the call, ask about: {'; '.join(off_script)}."
        if off_script
        else ""
    )

    return f"""\
You are {profile.get("name", "the candidate")}, a real person on a phone screening call. Speak
naturally and briefly, the way someone actually talks on the phone — not written prose.

BACKGROUND
{profile.get("background", "")}
{profile.get("years_experience", 0)} years of relevant experience. Skills: \
{", ".join(profile.get("skills", []))}.
Situation: {profile.get("situation", "")}. Location: {profile.get("location", "")}.

YOUR TRUE ANSWERS — answer consistently with these if asked, never contradict them, and never
volunteer any of this unless the question is actually asked:
{chr(10).join(facts_lines)}

{interest_line}

BEHAVIOUR
- Verbosity: {behaviour.get("verbosity", "normal")}
- Attitude: {behaviour.get("cooperativeness", "neutral")}
- {language_line}
{("- " + off_script_line) if off_script_line else ""}

RULES
- Stay in character at all times.
- Never volunteer information you were not asked for.
- If you decide to end the call yourself, end your final message with the exact token \
{_CANDIDATE_DONE_TOKEN} and say nothing after it.
"""


def _to_chat_messages(
    transcript: list[TranscriptTurn], *, speaking_as: Literal["agent", "candidate"]
) -> list[dict[str, str]]:
    """The same transcript, seen from one side: that side's own turns become "assistant", the
    other side's become "user"."""
    messages: list[dict[str, str]] = []
    for turn in transcript:
        role = "assistant" if turn.speaker == speaking_as else "user"
        messages.append({"role": role, "content": turn.text})
    return messages


def _strip_done_token(text: str, token: str) -> tuple[str, bool]:
    if token in text:
        return text.replace(token, "").strip(), True
    return text.strip(), False


async def _agent_turn(
    service: LLMService, system_prompt: str, transcript: list[TranscriptTurn]
) -> tuple[str, bool]:
    messages = [
        {"role": "system", "content": system_prompt},
        *_to_chat_messages(transcript, speaking_as="agent"),
    ]
    raw = await service.complete("simulator", messages, temperature=0.7)
    return _strip_done_token(raw, _AGENT_DONE_TOKEN)


async def _candidate_turn(
    service: LLMService, system_prompt: str, transcript: list[TranscriptTurn]
) -> tuple[str, bool]:
    messages = [
        {"role": "system", "content": system_prompt},
        *_to_chat_messages(transcript, speaking_as="candidate"),
    ]
    raw = await service.complete("simulator", messages, temperature=0.7)
    return _strip_done_token(raw, _CANDIDATE_DONE_TOKEN)


def _field_type(prop: dict[str, Any]) -> Any:
    prop_type = prop.get("type")
    if prop_type == "boolean":
        return bool
    if prop_type == "number":
        return float
    if prop_type == "string":
        enum = prop.get("enum")
        if enum:
            return Literal[tuple(enum)]
        return str
    return Any


def _build_result_model(result_schema: dict[str, Any]) -> type[BaseModel]:
    """A Pydantic model built fresh from the version's own result_schema, so the extraction
    call is validated exactly against what Hunar would validate the real call's result against.
    Only .model_dump() is ever called on instances of this — never per-field attribute access —
    so its dynamic shape does not need to be statically known."""
    properties = result_schema.get("properties", {})
    required = set(result_schema.get("required", []))
    fields: dict[str, Any] = {}
    for name, prop in properties.items():
        field_type = _field_type(prop)
        fields[name] = (field_type, ...) if name in required else (field_type | None, None)
    return create_model("ExtractedResult", __config__=ConfigDict(extra="allow"), **fields)


def _format_transcript(transcript: list[TranscriptTurn]) -> str:
    return "\n".join(f"{turn.speaker.upper()}: {turn.text}" for turn in transcript)


def _estimate_seconds(transcript: list[TranscriptTurn]) -> float:
    total_words = sum(len(turn.text.split()) for turn in transcript)
    boundaries = max(len(transcript) - 1, 0)
    return total_words / _WORDS_PER_SECOND + boundaries * _SECONDS_PER_TURN_BOUNDARY


async def simulate_call(
    agent_version: AgentVersion,
    persona: Persona,
    compiled: CompiledJD,
    *,
    llm: LLMService | None = None,
) -> SimulatedCall:
    """Run one rehearsal call between agent_version's actual prompt and this persona.

    `compiled` supplies role_title/locations for custom_data — the same data a real call's
    custom_data would carry — since AgentVersion itself does not store them separately (they're
    already baked as literal text into objective/introduction, and left as placeholders only in
    agent_prompt; see build_agent_prompt in jd_compiler.py).
    """
    service = llm or get_llm_service()

    custom_data = _custom_data(agent_version, persona, compiled)
    agent_prompt = _render(agent_version.agent_prompt, custom_data)
    introduction = _render(agent_version.introduction, custom_data)
    agent_system_prompt = _agent_system_prompt(agent_prompt)
    candidate_system_prompt = _candidate_system_prompt(persona, compiled)

    transcript: list[TranscriptTurn] = [TranscriptTurn(speaker="agent", text=introduction, turn=0)]

    while len(transcript) < MAX_TURNS:
        candidate_text, candidate_ended = await _candidate_turn(
            service, candidate_system_prompt, transcript
        )
        transcript.append(
            TranscriptTurn(speaker="candidate", text=candidate_text, turn=len(transcript))
        )
        if candidate_ended or len(transcript) >= MAX_TURNS:
            break

        agent_text, agent_concluded = await _agent_turn(service, agent_system_prompt, transcript)
        transcript.append(TranscriptTurn(speaker="agent", text=agent_text, turn=len(transcript)))
        if agent_concluded:
            break

    result_model = _build_result_model(agent_version.result_schema)
    extracted = await service.structured_complete(
        "simulator",
        [
            {"role": "system", "content": agent_version.result_prompt},
            {
                "role": "user",
                "content": f"Transcript of the completed call:\n\n{_format_transcript(transcript)}",
            },
        ],
        result_model,
    )

    return SimulatedCall(
        persona_id=persona.id,
        transcript=transcript,
        extracted_result=extracted.model_dump(mode="json"),
        turn_count=len(transcript),
        estimated_seconds=_estimate_seconds(transcript),
    )


async def run_rehearsal_cases(
    session: AsyncSession,
    run_id: uuid.UUID,
    agent_version: AgentVersion,
    compiled: CompiledJD,
    personas: list[Persona],
    *,
    llm: LLMService | None = None,
    concurrency: int = 3,
) -> list[RehearsalCase]:
    """Simulate every persona, up to `concurrency` at once, and persist each RehearsalCase the
    moment its simulation finishes.

    The concurrency is in the LLM work only: results are drained one at a time via
    asyncio.as_completed and committed in the driving coroutine, since an AsyncSession must not
    be used from more than one task at a time. That serialised drain is also what "persist each
    case as it completes" means in practice — a persona that fails after three others have
    already finished never costs those three their already-committed rows.
    """
    service = llm or get_llm_service()
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(persona: Persona) -> tuple[Persona, SimulatedCall]:
        async with semaphore:
            simulated = await simulate_call(agent_version, persona, compiled, llm=service)
        return persona, simulated

    tasks = [asyncio.ensure_future(_bounded(persona)) for persona in personas]

    cases: list[RehearsalCase] = []
    for task in asyncio.as_completed(tasks):
        try:
            persona, simulated = await task
        except Exception:
            logger.exception("rehearsal_case_simulation_failed", run_id=str(run_id))
            continue

        case = RehearsalCase(
            run_id=run_id,
            persona_id=persona.id,
            transcript=[turn.model_dump(mode="json") for turn in simulated.transcript],
            extracted_result=simulated.extracted_result,
            estimated_seconds=simulated.estimated_seconds,
            turn_count=simulated.turn_count,
        )
        session.add(case)
        await session.commit()
        cases.append(case)

    return cases
