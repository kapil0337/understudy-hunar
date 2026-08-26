from __future__ import annotations

import json

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.integrations.hunar.client import HunarClient
from app.models.agent_version import AgentVersion
from app.models.cache import ProviderCache
from app.models.enums import AgentVersionOrigin, Language
from app.models.job import Job
from app.schemas.compiled_jd import CompiledJD
from app.services.jd_compiler import (
    JDCompilationError,
    build_agent_version,
    build_result_schema,
    compile_jd,
    compiled_jd_cache_key,
    create_initial_version,
    create_patched_version,
    find_document_dependent_questions,
    next_version_no,
    publish_version,
)
from app.services.llm import InMemoryLLMCache, LLMService
from tests.services.conftest import JD_NAMES, FakeProvider, load_compiled_fixture, load_raw_jd

HUNAR_BASE_URL = "https://api.voice.hunar.ai/external/v1/"

pytestmark = pytest.mark.parametrize("jd_name", JD_NAMES)


def compiled_from_fixture(jd_name: str) -> CompiledJD:
    return CompiledJD.model_validate(load_compiled_fixture(jd_name))


def service_returning(jd_name: str, settings: object) -> LLMService:
    payload = load_compiled_fixture(jd_name)
    nvidia = FakeProvider("nvidia", [json.dumps(payload)])
    return LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=settings,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------------- fixtures


async def test_fixture_files_exist_and_are_readable(jd_name: str) -> None:
    raw = load_raw_jd(jd_name)
    assert len(raw.strip()) > 100


async def test_fixture_compiled_jd_validates(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    assert 4 <= len(compiled.screening_questions) <= 6
    assert len(compiled.facts_the_agent_may_state) >= 1


async def test_fixture_has_no_document_dependent_questions(jd_name: str) -> None:
    """The fixtures themselves must satisfy the 90-second/no-resume rule — they exist to
    demonstrate a compiler output that passes compile_jd's own check."""
    compiled = compiled_from_fixture(jd_name)
    assert find_document_dependent_questions(compiled) == []


# ---------------------------------------------------------------------- compile_jd()


async def test_compile_jd_returns_validated_compiled_jd(jd_name: str, llm_settings: object) -> None:
    service = service_returning(jd_name, llm_settings)
    raw = load_raw_jd(jd_name)

    compiled = await compile_jd(raw, llm=service)

    expected = compiled_from_fixture(jd_name)
    assert compiled.role_title == expected.role_title
    assert len(compiled.screening_questions) == len(expected.screening_questions)


async def test_compile_jd_reconciles_location_languages(jd_name: str, llm_settings: object) -> None:
    """Even if the raw fixture already lists the right languages, this proves the union path
    runs and never drops what the model proposed."""
    service = service_returning(jd_name, llm_settings)
    raw = load_raw_jd(jd_name)

    compiled = await compile_jd(raw, llm=service)

    # Every fixture location maps to a known regional language; it must be present.
    assert Language.ENGLISH in compiled.candidate_languages


async def test_compile_jd_uses_provider_cache_when_session_given(
    jd_name: str, llm_settings: object, db_session: AsyncSession
) -> None:
    service = service_returning(jd_name, llm_settings)
    raw = load_raw_jd(jd_name)

    first = await compile_jd(raw, session=db_session, llm=service)
    await db_session.flush()

    # Second call: provider has nothing left scripted, so a cache miss would raise.
    empty_service = LLMService(
        providers={},
        cache=InMemoryLLMCache(),
        settings=llm_settings,  # type: ignore[arg-type]
    )
    second = await compile_jd(raw, session=db_session, llm=empty_service)

    assert first == second


async def test_compile_jd_cache_is_keyed_by_content_not_identity(
    jd_name: str, llm_settings: object, db_session: AsyncSession
) -> None:
    """Whitespace-only edits must still hit the cache — compiled_jd_cache_key normalises."""
    service = service_returning(jd_name, llm_settings)
    raw = load_raw_jd(jd_name)

    await compile_jd(raw, session=db_session, llm=service)

    reformatted = "  ".join(raw.split("\n"))  # same words, different whitespace
    row = (
        await db_session.execute(
            select(ProviderCache).where(
                col(ProviderCache.key) == compiled_jd_cache_key(reformatted)
            )
        )
    ).first()
    assert row is not None  # same content hash as the original


async def test_compile_jd_rejects_document_dependent_output(
    jd_name: str, llm_settings: object
) -> None:
    payload = load_compiled_fixture(jd_name)
    payload["screening_questions"][0]["text"] = "Please email us a copy of your resume."
    nvidia = FakeProvider("nvidia", [json.dumps(payload)])
    service = LLMService(
        providers={"nvidia": nvidia},
        cache=InMemoryLLMCache(),
        settings=llm_settings,  # type: ignore[arg-type]
    )

    with pytest.raises(JDCompilationError, match="resume"):
        await compile_jd(load_raw_jd(jd_name), llm=service)


# --------------------------------------------------------------------- build_result_schema


async def test_result_schema_has_one_key_per_question_plus_standard_fields(
    jd_name: str,
) -> None:
    compiled = compiled_from_fixture(jd_name)
    schema = build_result_schema(compiled)

    question_ids = {q.id for q in compiled.screening_questions}
    standard = {"interested", "qualified", "earliest_start", "rejection_reason"}

    assert set(schema["properties"].keys()) == question_ids | standard
    assert set(schema["required"]) == question_ids | standard


async def test_result_schema_maps_answer_types_correctly(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    schema = build_result_schema(compiled)

    for question in compiled.screening_questions:
        prop = schema["properties"][question.id]
        if question.answer_type == "boolean":
            assert prop["type"] == "boolean"
        elif question.answer_type == "number":
            assert prop["type"] == "number"
        elif question.answer_type == "enum":
            assert prop["type"] == "string"
            assert prop["enum"] == question.options
        else:
            assert prop["type"] == "string"


async def test_result_schema_is_flat_no_nested_objects(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    schema = build_result_schema(compiled)

    for prop in schema["properties"].values():
        assert prop["type"] != "object"


# ---------------------------------------------------------------------- build_agent_version


async def test_agent_version_embeds_every_fact_and_nothing_extra_implied(
    jd_name: str,
) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.ENGLISH)

    for fact in compiled.facts_the_agent_may_state:
        assert fact in version.agent_prompt


async def test_agent_version_asks_every_screening_question(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.ENGLISH)

    for question in compiled.screening_questions:
        assert question.text in version.agent_prompt


async def test_agent_version_forbids_fabrication_explicitly(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.ENGLISH)

    lowered = version.agent_prompt.lower()
    assert "do not have that detail" in lowered or "don't have that detail" in lowered
    assert "never guess" in lowered or "never" in lowered


async def test_agent_version_targets_ninety_seconds(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.ENGLISH)

    assert "90 second" in version.agent_prompt or "90-second" in version.agent_prompt


async def test_agent_version_introduction_uses_template_variables(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.ENGLISH)

    assert "{persona_name}" in version.introduction
    assert "{callee_name}" in version.introduction


async def test_agent_version_result_schema_matches_build_result_schema(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.ENGLISH)

    assert version.result_schema == build_result_schema(compiled)


async def test_agent_version_stores_screening_questions_as_dicts(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.ENGLISH)

    assert len(version.screening_questions) == len(compiled.screening_questions)
    assert version.screening_questions[0]["id"] == compiled.screening_questions[0].id


async def test_agent_version_origin_defaults_to_compiled(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.ENGLISH)

    assert version.origin == AgentVersionOrigin.COMPILED


async def test_agent_version_language_is_set_from_argument(jd_name: str) -> None:
    compiled = compiled_from_fixture(jd_name)
    version = build_agent_version(compiled, Language.TAMIL)

    assert version.language == Language.TAMIL


# ---------------------------------------------------------------------------- versioning


async def test_compile_creates_version_one(jd_name: str, db_session: AsyncSession) -> None:
    job = Job(title="x", raw_jd=load_raw_jd(jd_name))
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)

    version = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)

    assert version.version_no == 1
    assert version.origin == AgentVersionOrigin.COMPILED


async def test_accepted_patch_creates_version_n_plus_1_not_edit(
    jd_name: str, db_session: AsyncSession
) -> None:
    job = Job(title="x", raw_jd=load_raw_jd(jd_name))
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)

    v1 = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    original_prompt = v1.agent_prompt

    v2 = await create_patched_version(db_session, v1, "A completely different prompt.")

    assert v2.version_no == 2
    assert v2.id != v1.id
    assert v2.origin == AgentVersionOrigin.PATCHED
    assert v2.agent_prompt == "A completely different prompt."
    # v1 must be untouched — nothing is edited in place.
    refreshed_v1 = await db_session.get(AgentVersion, v1.id)
    assert refreshed_v1 is not None
    assert refreshed_v1.agent_prompt == original_prompt
    assert refreshed_v1.version_no == 1


async def test_patched_version_does_not_inherit_hunar_agent_id(
    jd_name: str, db_session: AsyncSession
) -> None:
    """A new, unpublished version must not silently overwrite the previous Hunar agent."""
    job = Job(title="x", raw_jd=load_raw_jd(jd_name))
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)

    v1 = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    v1.hunar_agent_id = "agt_published_v1"
    db_session.add(v1)
    await db_session.flush()

    v2 = await create_patched_version(db_session, v1, "patched")

    assert v2.hunar_agent_id is None


async def test_versions_are_numbered_per_language_independently(
    jd_name: str, db_session: AsyncSession
) -> None:
    """unique(job_id, language, version_no) — versioning is per language, so English and Tamil
    can each be at v1 for the same job simultaneously."""
    job = Job(title="x", raw_jd=load_raw_jd(jd_name))
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)

    en_v1 = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    ta_v1 = await create_initial_version(db_session, job.id, compiled, Language.TAMIL)
    en_v2 = await create_patched_version(db_session, en_v1, "patched english")

    assert en_v1.version_no == 1
    assert ta_v1.version_no == 1
    assert en_v2.version_no == 2

    assert await next_version_no(db_session, job.id, Language.TAMIL) == 2
    assert await next_version_no(db_session, job.id, Language.ENGLISH) == 3


# ------------------------------------------------------------------------- publishing


@respx.mock
async def test_publish_creates_agent_and_stores_hunar_agent_id(
    jd_name: str, db_session: AsyncSession
) -> None:
    job = Job(title="Test Role", raw_jd=load_raw_jd(jd_name))
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)
    version = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    assert version.hunar_agent_id is None

    route = respx.post(f"{HUNAR_BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json={"id": "agt_new_1", "name": "whatever"})
    )

    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        client = HunarClient("test-key", client=transport)
        published = await publish_version(db_session, version, client)

    assert route.called
    assert published.hunar_agent_id == "agt_new_1"
    assert version.hunar_agent_id == "agt_new_1"  # same object, mutated in place


@respx.mock
async def test_publish_derives_a_hunar_name_from_job_title_since_no_name_column_exists(
    jd_name: str, db_session: AsyncSession
) -> None:
    """AgentVersion has no `name` field (see the agent_version table definition in
    CONTRIBUTING.md) — publish_version must derive Hunar's required `name` from data that actually
    exists rather than from a field that was never stored."""
    job = Job(title="Distinctive Job Title", raw_jd=load_raw_jd(jd_name))
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)
    version = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    assert not hasattr(version, "name")

    route = respx.post(f"{HUNAR_BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json={"id": "agt_new_2", "name": "whatever"})
    )

    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        client = HunarClient("test-key", client=transport)
        await publish_version(db_session, version, client)

    sent_name = json.loads(route.calls.last.request.content)["name"]
    assert "Distinctive Job Title" in sent_name
    assert str(version.version_no) in sent_name


@respx.mock
async def test_publish_updates_existing_agent_when_hunar_agent_id_set(
    jd_name: str, db_session: AsyncSession
) -> None:
    job = Job(title="Test Role", raw_jd=load_raw_jd(jd_name))
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)
    version = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    version.hunar_agent_id = "agt_existing"
    db_session.add(version)
    await db_session.flush()

    route = respx.put(f"{HUNAR_BASE_URL}agents/agt_existing/").mock(
        return_value=httpx.Response(200, json={"id": "agt_existing", "name": "whatever"})
    )

    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        client = HunarClient("test-key", client=transport)
        published = await publish_version(db_session, version, client)

    assert route.called
    assert published.hunar_agent_id == "agt_existing"


@respx.mock
async def test_publish_sends_full_field_set_on_update(
    jd_name: str, db_session: AsyncSession
) -> None:
    """Changing voice_persona or language requires resending the full documented field set
    (CONTRIBUTING.md) — the update path must never send a partial payload."""
    job = Job(title="Test Role", raw_jd=load_raw_jd(jd_name))
    db_session.add(job)
    await db_session.flush()
    compiled = compiled_from_fixture(jd_name)
    version = await create_initial_version(db_session, job.id, compiled, Language.ENGLISH)
    version.hunar_agent_id = "agt_existing"
    db_session.add(version)
    await db_session.flush()

    route = respx.put(f"{HUNAR_BASE_URL}agents/agt_existing/").mock(
        return_value=httpx.Response(200, json={"id": "agt_existing", "name": "whatever"})
    )

    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        client = HunarClient("test-key", client=transport)
        await publish_version(db_session, version, client)

    body = json.loads(route.calls.last.request.content)
    for required in (
        "name",
        "objective",
        "language",
        "voice_persona",
        "persona_name",
        "agent_prompt",
        "introduction",
        "result_prompt",
        "result_schema",
    ):
        assert required in body, f"{required} missing from publish update payload"
