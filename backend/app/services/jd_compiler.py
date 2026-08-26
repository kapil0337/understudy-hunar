"""Compile a raw job description into a CompiledJD, and turn that into an AgentVersion draft.

Two rules shape everything here:

  * Versions are immutable. Compiling produces v1; an accepted patch produces v n+1. Nothing is
    edited in place, so a rehearsal score always refers to an exact, retrievable prompt.
  * facts_the_agent_may_state is the whole faithfulness contract. The agent prompt states that
    list verbatim and forbids anything outside it, which is what lets scoring call a fabrication
    objectively rather than by feel.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.integrations.hunar.client import HunarClient
from app.integrations.hunar.models import AgentCreate, AgentUpdate
from app.models.agent_version import AgentVersion
from app.models.cache import ProviderCache
from app.models.enums import AgentVersionOrigin, Language, VoicePersona
from app.models.job import Job
from app.schemas.compiled_jd import CompiledJD
from app.services import guardrails as guardrails_service
from app.services.llm import LLMService, get_llm_service

logger = structlog.get_logger()

COMPILED_JD_CACHE_PROVIDER = "jd_compiler"

# Deterministic location -> language mapping. The model is asked to infer languages too, but
# this map is the authority: a city's regional language is a fact, not a judgement call, and
# getting it wrong means calling someone in a language they may not speak.
_CITY_LANGUAGES: dict[str, Language] = {
    "chennai": Language.TAMIL,
    "coimbatore": Language.TAMIL,
    "madurai": Language.TAMIL,
    "tamil nadu": Language.TAMIL,
    "bengaluru": Language.KANNADA,
    "bangalore": Language.KANNADA,
    "mysuru": Language.KANNADA,
    "mysore": Language.KANNADA,
    "karnataka": Language.KANNADA,
    "pune": Language.MARATHI,
    "mumbai": Language.MARATHI,
    "nagpur": Language.MARATHI,
    "nashik": Language.MARATHI,
    "maharashtra": Language.MARATHI,
    "hyderabad": Language.TELUGU,
    "vijayawada": Language.TELUGU,
    "visakhapatnam": Language.TELUGU,
    "telangana": Language.TELUGU,
    "andhra pradesh": Language.TELUGU,
    "kochi": Language.MALAYALAM,
    "thiruvananthapuram": Language.MALAYALAM,
    "kerala": Language.MALAYALAM,
    "ahmedabad": Language.GUJARATI,
    "surat": Language.GUJARATI,
    "vadodara": Language.GUJARATI,
    "gujarat": Language.GUJARATI,
    "kolkata": Language.BENGALI,
    "west bengal": Language.BENGALI,
    "delhi": Language.HINDI,
    "new delhi": Language.HINDI,
    "gurugram": Language.HINDI,
    "gurgaon": Language.HINDI,
    "noida": Language.HINDI,
    "jaipur": Language.HINDI,
    "lucknow": Language.HINDI,
    "indore": Language.HINDI,
    "bhopal": Language.HINDI,
}

# Heuristic backstop for "answerable in a 90-second call with no resume in hand". This does not
# replace the instruction in the prompt — it catches the obvious violations the model still
# sometimes produces, so they fail loudly at compile time rather than on a live call.
_DOCUMENT_DEPENDENT = re.compile(
    r"\b("
    r"upload|attach|email (?:us|me|your)|send (?:us|me|your|a copy)|"
    r"resume|cv\b|certificate number|licence number|license number|"
    r"aadhaar number|aadhar number|pan number|passport number|"
    r"exact date of|payslip|bank statement|document"
    r")\b",
    re.IGNORECASE,
)

_COMPILER_SYSTEM_PROMPT = """\
You compile raw job descriptions into structured hiring specs for a voice screening agent.

Output MUST satisfy the provided JSON schema exactly.

Rules that matter most:

1. screening_questions: between 4 and 6. EVERY question must be answerable out loud, from
   memory, in a 90-second phone call, by someone with no resume or documents in front of them.
   Ask "do you have a two-wheeler and a valid licence?" (boolean), never "what is your licence
   number?". Ask "how many years have you been riding commercially?" (number), never "email us
   your experience letter". Reject anything needing a document, a precise date, or a lookup.
   Use snake_case ids.

2. facts_the_agent_may_state: the complete list of claims the agent is permitted to make about
   this role — pay, shift, location, equipment provided, and so on. The agent may say NOTHING
   about the role beyond this list. Anything absent here counts as a fabrication when the
   rehearsal is scored, so include every fact a candidate would reasonably need, and include
   ONLY facts actually supported by the job description. Never invent a benefit or a number.

3. knockout_criteria: for every screening question whose why_it_matters states or implies it is
   a hard requirement (mandatory, required, must-have — not merely preferred or nice-to-have),
   add a knockout_criteria entry disqualifying the answer that fails it. A JD with an explicit
   "requirements"/"what we need" list almost always yields at least one knockout criterion —
   an empty knockout_criteria on such a JD is very likely a missed requirement, not a sign the
   role has none. Only reference ids that exist in screening_questions, and for enum questions
   only use values listed in that question's options.

   Worked example — a JD says "What we need: own two-wheeler in working condition, valid
   licence" and you write the screening question
     {"id": "has_two_wheeler", "answer_type": "boolean",
      "why_it_matters": "Own vehicle is mandatory for this role."}
   Because that requirement is mandatory, knockout_criteria MUST include
     {"question_id": "has_two_wheeler", "operator": "eq", "value": false}
   — a candidate who answers false is disqualified. Do this for EVERY mandatory requirement, not
   just the first. Do not stop after one; check every screening question against its own
   why_it_matters before deciding knockout_criteria is complete.

4. candidate_languages: Hunar language enums (ENGLISH, HINDI, TAMIL, TELUGU, KANNADA, MARATHI,
   MALAYALAM, GUJARATI, BENGALI) implied by the locations. Include the regional language of
   each location.

5. Do not invent salary, shift, or benefit details that the job description does not state.
   Use null for salary_range if it is not stated.
"""


def compiled_jd_cache_key(raw_jd: str) -> str:
    """Content hash of the raw JD. Whitespace-normalised so trivial edits still hit."""
    normalised = " ".join(raw_jd.split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def infer_languages_from_locations(locations: list[str]) -> list[Language]:
    """Regional languages implied by the locations, plus ENGLISH and HINDI as the common
    fallbacks for Indian metros. Deterministic on purpose — see _CITY_LANGUAGES."""
    found: list[Language] = []
    for location in locations:
        lowered = location.lower()
        for city, language in _CITY_LANGUAGES.items():
            if city in lowered and language not in found:
                found.append(language)

    ordered: list[Language] = [*found]
    for default in (Language.ENGLISH, Language.HINDI):
        if default not in ordered:
            ordered.append(default)
    return ordered


def find_document_dependent_questions(compiled: CompiledJD) -> list[str]:
    """Ids of questions that look like they need a document or a lookup to answer.

    Heuristic, and deliberately so: it is a cheap net for the obvious failures, not a proof of
    compliance. A clean result does not guarantee every question is answerable from memory.
    """
    return [
        question.id
        for question in compiled.screening_questions
        if _DOCUMENT_DEPENDENT.search(question.text)
    ]


class JDCompilationError(Exception):
    """The compiled JD came back structurally valid but violating a hard rule."""


async def compile_jd(
    raw_jd: str,
    *,
    session: AsyncSession | None = None,
    llm: LLMService | None = None,
    use_cache: bool = True,
) -> CompiledJD:
    """Compile a raw JD into a CompiledJD.

    Cached by content hash in provider_cache, on top of the LLM-level cache: this one survives
    a change of model or prompt wording, which the LLM cache key deliberately does not.
    """
    service = llm or get_llm_service()
    key = compiled_jd_cache_key(raw_jd)

    if use_cache and session is not None:
        cached = await _get_cached_compilation(session, key)
        if cached is not None:
            logger.info("compiled_jd_cache_hit", key=key[:12])
            return CompiledJD.model_validate(cached)

    compiled = await service.structured_complete(
        "compiler",
        [
            {"role": "system", "content": _COMPILER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Job description:\n\n{raw_jd.strip()}"},
        ],
        CompiledJD,
    )

    offenders = find_document_dependent_questions(compiled)
    if offenders:
        raise JDCompilationError(
            "screening questions must be answerable in a 90-second call with no resume in "
            f"hand; these appear to need a document or lookup: {', '.join(offenders)}"
        )

    compiled = _reconcile_languages(compiled)

    if use_cache and session is not None:
        await _store_compilation(session, key, compiled)

    return compiled


def _reconcile_languages(compiled: CompiledJD) -> CompiledJD:
    """Union the model's languages with the deterministic location-derived set.

    Union rather than replace: the JD may name a language the location map does not imply
    (a Hindi-speaking role in Chennai, say), and dropping that would be worse than adding one.
    """
    derived = infer_languages_from_locations(compiled.locations)
    merged: list[Language] = [*compiled.candidate_languages]
    for language in derived:
        if language not in merged:
            merged.append(language)

    if merged != compiled.candidate_languages:
        logger.info(
            "compiled_jd_languages_reconciled",
            model_proposed=[lang.value for lang in compiled.candidate_languages],
            final=[lang.value for lang in merged],
        )
    return compiled.model_copy(update={"candidate_languages": merged})


async def _get_cached_compilation(session: AsyncSession, key: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(ProviderCache).where(
                col(ProviderCache.key) == key,
                col(ProviderCache.provider) == COMPILED_JD_CACHE_PROVIDER,
            )
        )
    ).scalar_one_or_none()
    return row.response if row is not None else None


async def _store_compilation(session: AsyncSession, key: str, compiled: CompiledJD) -> None:
    # fetched_at is set explicitly: this is a Core-level insert, so it bypasses the ORM
    # instance construction that would normally apply the column's default_factory — without
    # this the NOT NULL constraint fails on every write (see the identical fix in
    # app/services/llm.py's DatabaseLLMCache.set).
    await session.execute(
        pg_insert(ProviderCache)
        .values(
            key=key,
            provider=COMPILED_JD_CACHE_PROVIDER,
            response=compiled.model_dump(mode="json"),
            fetched_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["key"])
    )
    await session.flush()


# --------------------------------------------------------------------- agent build


def build_result_schema(compiled: CompiledJD) -> dict[str, Any]:
    """A FLAT result schema: one key per screening question id, plus the four standard
    outcome fields. Flat because Hunar shapes `result` from this and nested objects are far
    more likely to come back malformed or partially filled."""
    properties: dict[str, Any] = {}

    for question in compiled.screening_questions:
        if question.answer_type == "boolean":
            spec: dict[str, Any] = {"type": "boolean"}
        elif question.answer_type == "number":
            spec = {"type": "number"}
        elif question.answer_type == "enum":
            spec = {"type": "string", "enum": list(question.options or [])}
        else:
            spec = {"type": "string"}
        spec["description"] = question.text
        properties[question.id] = spec

    properties["interested"] = {
        "type": "boolean",
        "description": "Did the candidate express interest in proceeding?",
    }
    properties["qualified"] = {
        "type": "boolean",
        "description": "Did the candidate pass every knockout criterion?",
    }
    properties["earliest_start"] = {
        "type": "string",
        "description": "When the candidate said they could start, in their own words.",
    }
    properties["rejection_reason"] = {
        "type": "string",
        "description": "If not qualified or not interested, the reason. Empty otherwise.",
    }

    return {
        "type": "object",
        "properties": properties,
        "required": [*properties.keys()],
    }


def build_agent_prompt(compiled: CompiledJD, language: Language) -> str:
    """The agent's operating instructions.

    facts_the_agent_may_state is embedded verbatim and framed as an exhaustive whitelist,
    because that framing is what the faithfulness metric later scores against.
    """
    questions = "\n".join(
        f"{index}. ({question.answer_type}) {question.text}"
        + (
            f"\n   Offer these options: {', '.join(question.options)}"
            if question.answer_type == "enum" and question.options
            else ""
        )
        for index, question in enumerate(compiled.screening_questions, start=1)
    )
    facts = "\n".join(f"- {fact}" for fact in compiled.facts_the_agent_may_state)

    return f"""\
You are {{persona_name}}, a recruiter calling {{callee_name}} about a {{role_title}} role in \
{{role_location}}. Speak {language.value.title()}.

GOAL
Screen this candidate in under 90 seconds. Be warm, direct, and quick. This is a phone call:
short sentences, one question at a time, no lists read aloud.

WHAT YOU MAY SAY ABOUT THE ROLE
You may state ONLY the following facts. This list is exhaustive.
{facts}

If asked anything not covered above — exact pay for their case, contract terms, start date
guarantees, anything at all — say you do not have that detail and a human recruiter will
follow up. NEVER guess, estimate, extrapolate, or invent a fact about this role. Saying "I
don't have that detail" is always the correct answer when the fact is not on the list above.

SCREENING QUESTIONS — ask these in order, all of them:
{questions}

Ask them conversationally, not as a form. Accept short answers and move on. Do not ask for
documents, numbers they would need to look up, or anything they could not answer from memory.

IF THEY ARE NOT INTERESTED
Thank them sincerely, do not push or re-pitch more than once, confirm they want no further
contact if they say so, and end the call politely.

CLOSING
Summarise the next step in one sentence, thank them, and end. Target under 90 seconds total.
"""


def build_introduction(compiled: CompiledJD) -> str:
    return (
        "Hi {callee_name}, this is {persona_name} calling about a "
        f"{compiled.role_title} opening"
        + (f" in {compiled.locations[0]}" if compiled.locations else "")
        + ". Do you have ninety seconds to talk?"
    )


def build_result_prompt(compiled: CompiledJD) -> str:
    ids = ", ".join(question.id for question in compiled.screening_questions)
    return f"""\
From this call, extract exactly these fields: {ids}, interested, qualified, earliest_start,
rejection_reason.

Use only what the candidate actually said. If a question was not asked or not answered, leave
that field empty rather than guessing. Set qualified to false if any knockout criterion was
failed. Set rejection_reason only when interested or qualified is false.
"""


def build_agent_version(
    compiled: CompiledJD,
    language: Language,
    *,
    job_id: Any = None,
    version_no: int = 1,
    voice_persona: VoicePersona = VoicePersona.NEHA,
    persona_name: str = "Neha",
    origin: AgentVersionOrigin = AgentVersionOrigin.COMPILED,
) -> AgentVersion:
    """Build an AgentVersion draft. Not persisted — the caller decides whether to save it."""
    location = compiled.locations[0] if compiled.locations else "the listed location"

    return AgentVersion(
        job_id=job_id,
        version_no=version_no,
        language=language,
        voice_persona=voice_persona,
        persona_name=persona_name,
        objective=(
            f"Screen candidates for {compiled.role_title} in {location}: confirm interest, "
            "ask the screening questions, and capture a structured result in under 90 seconds."
        ),
        agent_prompt=build_agent_prompt(compiled, language),
        introduction=build_introduction(compiled),
        result_prompt=build_result_prompt(compiled),
        result_schema=build_result_schema(compiled),
        screening_questions=[
            question.model_dump(mode="json") for question in compiled.screening_questions
        ],
        origin=origin,
    )


# ---------------------------------------------------------------------- versioning


async def next_version_no(session: AsyncSession, job_id: Any, language: Language) -> int:
    """The next version number for (job, language). Versions are per-language because the
    unique constraint is (job_id, language, version_no)."""
    current = (
        await session.execute(
            select(func.max(AgentVersion.version_no)).where(
                col(AgentVersion.job_id) == job_id,
                col(AgentVersion.language) == language,
            )
        )
    ).scalar_one_or_none()
    return (current or 0) + 1


async def create_initial_version(
    session: AsyncSession,
    job_id: Any,
    compiled: CompiledJD,
    language: Language,
    **kwargs: Any,
) -> AgentVersion:
    """Compile-time v1 (or the next free number if one already exists)."""
    version = build_agent_version(
        compiled,
        language,
        job_id=job_id,
        version_no=await next_version_no(session, job_id, language),
        origin=AgentVersionOrigin.COMPILED,
        **kwargs,
    )
    session.add(version)
    await session.flush()
    return version


async def create_patched_version(
    session: AsyncSession,
    base: AgentVersion,
    proposed_agent_prompt: str,
) -> AgentVersion:
    """Apply an accepted patch as a NEW version.

    The base version is copied field by field with only agent_prompt replaced. Nothing is
    edited in place, so the rehearsal that produced the patch still points at the exact prompt
    it scored.
    """
    version = AgentVersion(
        job_id=base.job_id,
        version_no=await next_version_no(session, base.job_id, base.language),
        language=base.language,
        voice_persona=base.voice_persona,
        persona_name=base.persona_name,
        objective=base.objective,
        agent_prompt=proposed_agent_prompt,
        introduction=base.introduction,
        result_prompt=base.result_prompt,
        result_schema=base.result_schema,
        screening_questions=base.screening_questions,
        # Deliberately NOT copied: the new version is not published yet, and reusing the base's
        # hunar_agent_id would make publishing silently overwrite the previous agent.
        hunar_agent_id=None,
        origin=AgentVersionOrigin.PATCHED,
    )
    session.add(version)
    await session.flush()
    return version


async def publish_version(
    session: AsyncSession,
    version: AgentVersion,
    client: HunarClient,
    *,
    custom_variables: list[str] | None = None,
) -> AgentVersion:
    """Push a version to Hunar and record the resulting hunar_agent_id.

    Creates when the version has no hunar_agent_id, updates otherwise. The update path sends
    the full documented field set, since changing voice_persona or language requires it.

    AgentVersion has no `name` column of its own (see CLAUDE.md's field list) — Hunar's `name`
    is a display label with no equivalent in our schema, so it is derived here from the job's
    title plus the version's own identity rather than invented at build time and stored.
    """
    variables = custom_variables or ["callee_name", "role_title", "role_location"]
    display_name = await _hunar_display_name(session, version)

    if version.hunar_agent_id is None:
        agent = await client.create_agent(
            AgentCreate(
                name=display_name,
                language=version.language.value,
                voice_persona=version.voice_persona.value,
                persona_name=version.persona_name,
                agent_prompt=version.agent_prompt,
                objective=version.objective,
                introduction=version.introduction,
                result_prompt=version.result_prompt,
                result_schema=version.result_schema,
                custom_variables=variables,
                retry_config=guardrails_service.RETRY_CONFIG,
                guardrails=guardrails_service.GUARDRAILS,
            )
        )
        logger.info("agent_version_published", version_id=str(version.id), created=True)
    else:
        agent = await client.update_agent(
            version.hunar_agent_id,
            AgentUpdate(
                name=display_name,
                objective=version.objective,
                language=version.language.value,
                voice_persona=version.voice_persona.value,
                persona_name=version.persona_name,
                agent_prompt=version.agent_prompt,
                introduction=version.introduction,
                result_prompt=version.result_prompt,
                result_schema=version.result_schema,
                custom_variables=variables,
                retry_config=guardrails_service.RETRY_CONFIG,
                guardrails=guardrails_service.GUARDRAILS,
            ),
        )
        logger.info("agent_version_published", version_id=str(version.id), created=False)

    version.hunar_agent_id = agent.id
    session.add(version)
    await session.flush()
    return version


async def _hunar_display_name(session: AsyncSession, version: AgentVersion) -> str:
    job = await session.get(Job, version.job_id)
    role_title = job.title if job is not None else "Untitled role"
    return (
        f"{role_title} — {version.persona_name} v{version.version_no} "
        f"({version.language.value.title()})"
    )
