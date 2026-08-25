from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.hunar.client import BASE_URL as HUNAR_BASE_URL
from app.models.persona import Persona
from app.services.llm import InMemoryLLMCache, LLMService, set_llm_service
from app.services.outreach import BLOCK_NO_PHONE
from tests.services.conftest import FakeProvider, load_compiled_fixture, load_raw_jd


@pytest.fixture(autouse=True)
def _reset_llm_service() -> Iterator[None]:
    yield
    set_llm_service(None)


def _install_compiler_llm(jd_name: str) -> None:
    payload = load_compiled_fixture(jd_name)
    provider = FakeProvider("nvidia", [json.dumps(payload)])
    set_llm_service(LLMService(providers={"nvidia": provider}, cache=InMemoryLLMCache()))


async def _create_job(client: httpx.AsyncClient) -> str:
    resp = await client.post("/jobs", json={"title": "placeholder", "raw_jd": "placeholder text"})
    assert resp.status_code == 201
    return str(resp.json()["id"])


async def _compile_requirements(
    client: httpx.AsyncClient, job_id: str, jd_name: str = "delivery_rider_chennai"
) -> None:
    _install_compiler_llm(jd_name)
    resp = await client.put(f"/jobs/{job_id}/requirements", json={"raw_jd": load_raw_jd(jd_name)})
    assert resp.status_code == 200


# --------------------------------------------------------------------------------------- jobs


async def test_create_get_list_job(api_client: httpx.AsyncClient) -> None:
    created = await api_client.post("/jobs", json={"title": "Delivery Rider", "raw_jd": "jd"})
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert created.json()["compiled"] is None

    got = await api_client.get(f"/jobs/{job_id}")
    assert got.status_code == 200
    assert got.json()["title"] == "Delivery Rider"

    listed = await api_client.get("/jobs")
    assert listed.status_code == 200
    assert any(j["id"] == job_id for j in listed.json())


async def test_get_unknown_job_404(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get(f"/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


# ------------------------------------------------------------------------------- requirements


async def test_requirements_update_compiles_and_creates_draft_versions(
    api_client: httpx.AsyncClient,
) -> None:
    job_id = await _create_job(api_client)
    _install_compiler_llm("delivery_rider_chennai")

    resp = await api_client.put(
        f"/jobs/{job_id}/requirements",
        json={"raw_jd": load_raw_jd("delivery_rider_chennai")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert len(body["versions"]) >= 1
    assert all(v["version_no"] == 1 for v in body["versions"])
    assert all(v["hunar_agent_id"] is None for v in body["versions"])  # not published yet

    versions = (await api_client.get(f"/jobs/{job_id}/versions")).json()
    assert len(versions) == len(body["versions"])
    assert all(v["latest_composite_score"] is None for v in versions)  # never rehearsed


async def test_source_before_compile_returns_409(api_client: httpx.AsyncClient) -> None:
    job_id = await _create_job(api_client)
    resp = await api_client.post(f"/jobs/{job_id}/source", json={})
    assert resp.status_code == 409


# --------------------------------------------------------------------------------- candidates


async def test_source_and_list_candidates_best_match_first(api_client: httpx.AsyncClient) -> None:
    job_id = await _create_job(api_client)
    await _compile_requirements(api_client, job_id)

    resp = await api_client.post(f"/jobs/{job_id}/source", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "fixtures"
    assert body["cached"] is False
    assert len(body["candidates"]) > 0
    assert all(c["match_score"] is not None for c in body["candidates"])
    assert all(c["phone_e164"] is None for c in body["candidates"])  # never from sourcing

    listed = (await api_client.get(f"/jobs/{job_id}/candidates")).json()
    assert len(listed) == len(body["candidates"])
    scores = [c["match_score"] for c in listed]
    assert scores == sorted(scores, reverse=True)


async def test_sourcing_twice_does_not_duplicate_candidates(api_client: httpx.AsyncClient) -> None:
    job_id = await _create_job(api_client)
    await _compile_requirements(api_client, job_id)

    first = (await api_client.post(f"/jobs/{job_id}/source", json={})).json()
    second = (await api_client.post(f"/jobs/{job_id}/source", json={})).json()

    listed = (await api_client.get(f"/jobs/{job_id}/candidates")).json()
    assert len(listed) == len(first["candidates"]) == len(second["candidates"])


async def test_personas_returns_existing_rows_without_an_llm_call(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job_id = await _create_job(api_client)
    await _compile_requirements(api_client, job_id)

    persona = Persona(
        job_id=uuid.UUID(job_id),
        archetype="QUALIFIED_EAGER",
        profile={"name": "Test Persona"},
        ground_truth={"qualified": True},
        behaviour={"verbosity": "normal"},
    )
    db_session.add(persona)
    await db_session.flush()

    # No LLM installed for this call — a regeneration attempt would raise on the FakeProvider
    # being empty, so a 200 here proves the existing row was returned rather than regenerated.
    resp = await api_client.get(f"/jobs/{job_id}/personas")
    assert resp.status_code == 200
    archetypes = [p["archetype"] for p in resp.json()]
    assert archetypes == ["QUALIFIED_EAGER"]


# -------------------------------------------------------------------------- call / board / export


@respx.mock
async def test_call_launch_guard_board_and_export(
    api_client_with_hunar: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job_id = await _create_job(api_client_with_hunar)
    await _compile_requirements(api_client_with_hunar, job_id)

    sourced = (await api_client_with_hunar.post(f"/jobs/{job_id}/source", json={})).json()
    candidates = sourced["candidates"]
    assert len(candidates) >= 2
    consented_id = candidates[0]["id"]
    unconsented_id = candidates[1]["id"]

    consent_resp = await api_client_with_hunar.post(
        f"/candidates/{consented_id}/consent", json={"phone_e164": "+919876543210"}
    )
    assert consent_resp.status_code == 200
    assert consent_resp.json()["consent_recorded_at"] is not None

    respx.post(f"{HUNAR_BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json={"id": "agt_1", "name": "Test Agent"})
    )
    respx.get(f"{HUNAR_BASE_URL}agents/agt_1/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "agt_1",
                "name": "Test Agent",
                "custom_variables": ["callee_name", "role_title", "role_location"],
            },
        )
    )
    respx.post(f"{HUNAR_BASE_URL}calls/").mock(
        return_value=httpx.Response(200, json={"id": "cal_1", "status": "NOT_STARTED"})
    )

    launch = await api_client_with_hunar.post(
        f"/jobs/{job_id}/call", json={"candidate_ids": [consented_id, unconsented_id]}
    )
    assert launch.status_code == 200
    launch_body = launch.json()
    assert len(launch_body["queued"]) == 1
    assert launch_body["queued"][0]["candidate_id"] == consented_id
    assert len(launch_body["blocked"]) == 1
    assert launch_body["blocked"][0]["candidate_id"] == unconsented_id
    assert launch_body["blocked"][0]["reason"] == BLOCK_NO_PHONE

    board = await api_client_with_hunar.get(f"/jobs/{job_id}/board")
    assert board.status_code == 200
    board_body = board.json()
    assert board_body["job_id"] == job_id
    queued_row = next(r for r in board_body["rows"] if r["candidate_id"] == consented_id)
    assert queued_row["status"] == "NOT_STARTED"
    assert queued_row["outreach_id"] is not None

    export = await api_client_with_hunar.get(f"/jobs/{job_id}/export")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "candidate_id" in export.text
    assert "has_two_wheeler" in export.text  # a screening question column
    assert consented_id in export.text
