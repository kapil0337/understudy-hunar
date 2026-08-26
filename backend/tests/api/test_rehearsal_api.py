from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_version import AgentVersion
from app.models.enums import Language
from app.models.job import Job
from app.models.rehearsal import RehearsalRun
from app.schemas.compiled_jd import CompiledJD
from app.services.jd_compiler import create_initial_version
from app.services.llm import InMemoryLLMCache, LLMService, set_llm_service
from tests.api.conftest import run_pending_background_job
from tests.services.conftest import FakeProvider, load_compiled_fixture

ADDITION = "\nREMEMBER: never invent a number that is not in the approved facts list."


@pytest.fixture(autouse=True)
def _reset_llm_service() -> Iterator[None]:
    yield
    set_llm_service(None)


def _install_llm(responses: list[Any]) -> None:
    provider = FakeProvider("nvidia", responses)
    set_llm_service(LLMService(providers={"nvidia": provider}, cache=InMemoryLLMCache()))


async def _seed_version(session: AsyncSession) -> tuple[Job, AgentVersion, CompiledJD]:
    compiled = CompiledJD.model_validate(load_compiled_fixture("delivery_rider_chennai"))
    job = Job(
        title=compiled.role_title, raw_jd="irrelevant", compiled=compiled.model_dump(mode="json")
    )
    session.add(job)
    await session.flush()
    version = await create_initial_version(session, job.id, compiled, Language.ENGLISH)
    await session.flush()
    return job, version, compiled


def _scores_with_failures(failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "composite": 80.0,
        "extraction_accuracy": {"score": 100.0, "fields": []},
        "coverage": {"score": 80.0, "cases": []},
        "faithfulness": {"score": 100.0, "cases": []},
        "efficiency": {"score": 100.0, "cases": []},
        "failures": failures,
    }


# ------------------------------------------------------------------------------- rehearse


async def test_rehearse_returns_202_with_pending_run(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # The actual simulation is deferred to a BackgroundJob picked up by app/worker.py (a
    # separate process in production) — this test never processes it, so the run stays
    # PENDING. The reuse mechanics rehearse_in_background depends on are covered directly in
    # tests/services/rehearsal/test_run.py instead.
    _, version, _ = await _seed_version(db_session)
    await db_session.commit()

    resp = await api_client.post(f"/versions/{version.id}/rehearse")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "PENDING"

    run_resp = await api_client.get(f"/runs/{body['run_id']}")
    assert run_resp.status_code == 200
    assert run_resp.json()["agent_version_id"] == str(version.id)
    assert run_resp.json()["status"] == "PENDING"


async def test_rehearse_unknown_version_404(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.post(f"/versions/{uuid.uuid4()}/rehearse")
    assert resp.status_code == 404


# ----------------------------------------------------------------------------------- runs


async def test_get_run_404(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get(f"/runs/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_get_case_404(api_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    _, version, _ = await _seed_version(db_session)
    run = RehearsalRun(agent_version_id=version.id, status="COMPLETED")
    db_session.add(run)
    await db_session.commit()

    resp = await api_client.get(f"/runs/{run.id}/cases/{uuid.uuid4()}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------------- patch


async def test_propose_patch_happy_path(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job, version, compiled = await _seed_version(db_session)
    run = RehearsalRun(
        agent_version_id=version.id,
        status="COMPLETED",
        scores=_scores_with_failures(
            [
                {
                    "persona_id": str(uuid.uuid4()),
                    "metric": "coverage",
                    "severity": "major",
                    "description": "never asked about licence",
                    "transcript_excerpt": "",
                }
            ]
        ),
    )
    db_session.add(run)
    await db_session.commit()

    revised_prompt = version.agent_prompt + ADDITION
    payload = {
        "revised_agent_prompt": revised_prompt,
        "rationale": [
            {
                "failure_id": "1",
                "change_summary": "reinforced the no-invented-numbers rule",
                "quoted_new_text": ADDITION.strip(),
            }
        ],
    }
    _install_llm([json.dumps(payload)])

    resp = await api_client.post(f"/runs/{run.id}/patch")
    assert resp.status_code == 202
    background_job_id = resp.json()["background_job_id"]

    job_row = await run_pending_background_job(db_session)
    assert job_row.id == uuid.UUID(background_job_id)
    assert job_row.status == "COMPLETED", job_row.error
    assert job_row.result is not None
    patch_id = job_row.result["patch_id"]

    patch_resp = await api_client.get(f"/patches/{patch_id}")
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["run_id"] == str(run.id)
    assert body["accepted"] is False
    assert ADDITION.strip() in body["proposed_agent_prompt"]


async def test_propose_patch_unknown_run_404(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.post(f"/runs/{uuid.uuid4()}/patch")
    assert resp.status_code == 404


async def test_propose_patch_unscored_run_fails_the_background_job(
    api_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # propose_patch's own "has this run been scored" check now runs inside app/worker.py
    # (see _handle_propose_patch) rather than synchronously in the route, since proposing a
    # patch is an LLM call — the route only fails fast on a missing job/compiled JD.
    _, version, _ = await _seed_version(db_session)
    run = RehearsalRun(agent_version_id=version.id, status="RUNNING", scores=None)
    db_session.add(run)
    await db_session.commit()

    resp = await api_client.post(f"/runs/{run.id}/patch")
    assert resp.status_code == 202

    job_row = await run_pending_background_job(db_session)
    assert job_row.status == "FAILED"
    assert "not been scored" in (job_row.error or "")


# --------------------------------------------------------------------------------- accept


async def test_accept_unknown_patch_404(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.post(f"/patches/{uuid.uuid4()}/accept")
    assert resp.status_code == 404
