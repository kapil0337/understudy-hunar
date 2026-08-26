from __future__ import annotations

import httpx
import pytest
import respx

from app.integrations.hunar.client import HunarClient
from app.integrations.hunar.exceptions import (
    HunarAPIError,
    HunarNotFound,
    HunarQuotaExhausted,
    HunarTelephonyError,
    HunarUnauthorized,
    HunarValidationError,
)
from app.integrations.hunar.models import AgentCreate, AgentUpdate, CallCreate
from tests.integrations.conftest import BASE_URL, TEST_API_KEY, load_fixture

# --------------------------------------------------------------------------- agents


@respx.mock
async def test_list_agents(hunar_client: HunarClient) -> None:
    route = respx.get(f"{BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json=load_fixture("agents_list.json"))
    )

    page = await hunar_client.list_agents()

    assert route.called
    assert page.count == 53
    assert len(page.results) == 20
    assert page.results[0].name == "Delivery Rider — Neha v1 (English)"
    assert page.results[0].language == "ENGLISH"
    assert page.results[0].custom_variables == ["role_location", "role_title"]


@respx.mock
async def test_list_agents_sends_api_key_header(hunar_client: HunarClient) -> None:
    route = respx.get(f"{BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json=load_fixture("agents_list.json"))
    )

    await hunar_client.list_agents()

    assert route.calls.last.request.headers["X-API-Key"] == TEST_API_KEY


@respx.mock
async def test_get_agent(hunar_client: HunarClient) -> None:
    fixture = load_fixture("agent_detail.json")
    agent_id = fixture["id"]
    route = respx.get(f"{BASE_URL}agents/{agent_id}/").mock(
        return_value=httpx.Response(200, json=fixture)
    )

    agent = await hunar_client.get_agent(agent_id)

    assert route.called
    assert agent.id == agent_id
    assert agent.voice_persona == "NEHA"
    assert agent.result_schema is not None


@respx.mock
async def test_create_agent_posts_full_payload(hunar_client: HunarClient) -> None:
    route = respx.post(f"{BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json=load_fixture("agent_created.json"))
    )

    agent = await hunar_client.create_agent(
        AgentCreate(
            name="Understudy Screener (EN)",
            language="ENGLISH",
            voice_persona="NEHA",
            agent_prompt="You are a recruiter.",
            objective="Screen the candidate.",
            introduction="Hi there.",
            result_prompt="Summarise.",
            result_schema={"type": "object"},
        )
    )

    assert agent.id
    sent = route.calls.last.request
    body = sent.read().decode()
    for required in (
        "name",
        "language",
        "voice_persona",
        "agent_prompt",
        "objective",
        "introduction",
        "result_prompt",
        "result_schema",
    ):
        assert required in body, f"{required} missing from create payload"


@respx.mock
async def test_create_agent_omits_unset_optional_blocks(hunar_client: HunarClient) -> None:
    """retry_config/guardrails must be absent rather than null when unset — an explicit null
    is not the same as 'inherit org defaults'."""
    route = respx.post(f"{BASE_URL}agents/").mock(
        return_value=httpx.Response(200, json=load_fixture("agent_created.json"))
    )

    await hunar_client.create_agent(
        AgentCreate(
            name="A",
            language="ENGLISH",
            voice_persona="NEHA",
            agent_prompt="p",
            objective="o",
            introduction="i",
            result_prompt="r",
            result_schema={},
        )
    )

    body = route.calls.last.request.read().decode()
    assert "retry_config" not in body
    assert "guardrails" not in body
    assert "callback_config" not in body


@respx.mock
async def test_update_agent(hunar_client: HunarClient) -> None:
    fixture = load_fixture("agent_updated.json")
    agent_id = fixture["id"]
    route = respx.put(f"{BASE_URL}agents/{agent_id}/").mock(
        return_value=httpx.Response(200, json=fixture)
    )

    agent = await hunar_client.update_agent(
        agent_id,
        AgentUpdate(
            name="Understudy Screener (EN)",
            objective="Screen the candidate.",
            language="ENGLISH",
            voice_persona="ROY",
            persona_name="Roy",
            agent_prompt="You are a recruiter.",
            introduction="Hi there.",
            result_prompt="Summarise.",
            result_schema={"type": "object"},
        ),
    )

    assert agent.voice_persona == "ROY"
    # A persona change must resend the whole documented field set, not a partial patch.
    body = route.calls.last.request.read().decode()
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
        assert required in body, f"{required} missing from update payload"


# ---------------------------------------------------------------------------- calls


@respx.mock
async def test_create_call(hunar_client: HunarClient) -> None:
    route = respx.post(f"{BASE_URL}calls/").mock(
        return_value=httpx.Response(200, json=load_fixture("call_created.json"))
    )

    call = await hunar_client.create_call(
        CallCreate(
            agent_id="agt_00000000000000000000000001",
            callee_name="Test Candidate",
            mobile_number="+919876543210",
            custom_data={"candidate_name": "Test Candidate", "role_title": "Backend Engineer"},
            request_id="job1234-cand5678-a1",
        )
    )

    assert route.called
    assert call.status == "NOT_STARTED"
    assert call.request_id == "job1234-cand5678-a1"


@respx.mock
async def test_list_calls(hunar_client: HunarClient) -> None:
    respx.get(f"{BASE_URL}calls/").mock(
        return_value=httpx.Response(200, json=load_fixture("calls_list.json"))
    )

    page = await hunar_client.list_calls()

    assert page.count == 488
    # Not pinned to page.results[0]: it is whichever call is most recent on the live account at
    # capture time, which can be one still in progress rather than COMPLETED.
    assert any(call.status == "COMPLETED" for call in page.results)


@respx.mock
async def test_list_calls_forwards_query_params(hunar_client: HunarClient) -> None:
    route = respx.get(f"{BASE_URL}calls/").mock(
        return_value=httpx.Response(200, json=load_fixture("calls_list.json"))
    )

    await hunar_client.list_calls(agent_id="agt_1", status="COMPLETED")

    assert dict(route.calls.last.request.url.params) == {
        "agent_id": "agt_1",
        "status": "COMPLETED",
    }


@respx.mock
async def test_get_call_exposes_result_and_recording_but_no_transcript(
    hunar_client: HunarClient,
) -> None:
    """Uses one specific completed call from calls_list.json rather than call_detail.json:
    the latter always reflects whichever call is most recent on the live account, which can be
    a call still in progress (null result/recording) depending on when it was captured."""
    calls = load_fixture("calls_list.json")["results"]
    fixture = next(c for c in calls if c["id"] == "cal_00000000000000000000000004")
    call_id = fixture["id"]
    respx.get(f"{BASE_URL}calls/{call_id}/").mock(return_value=httpx.Response(200, json=fixture))

    call = await hunar_client.get_call(call_id)

    assert call.result == {
        "summary": "NOT AVAILABLE",
        "reachable": "NOT AVAILABLE",
        "interested": "NOT AVAILABLE",
        "current_ctc": "NOT AVAILABLE",
        "expected_ctc": "NOT AVAILABLE",
        "role_interests": "NOT AVAILABLE",
        "career_interests": "NOT AVAILABLE",
        "negotiation_range": "NOT AVAILABLE",
        "open_to_negotiation": "NOT AVAILABLE",
        "overall_recommendation": "NOT AVAILABLE",
    }
    assert call.recording_url is not None
    # There is NO transcript field in the Hunar API (CONTRIBUTING.md); nothing should invent one.
    assert not hasattr(call, "transcript")


@respx.mock
async def test_get_call_maps_response_retry_field_name(hunar_client: HunarClient) -> None:
    """Requests send max_retry_count; responses come back as max_retries (CONTRIBUTING.md).

    The captured call never retried, so its real retry_config.max_retries is null — that field
    is overridden here to demonstrate the mapping against a call that did.
    """
    fixture = load_fixture("call_detail.json")
    fixture["retry_config"] = {"max_retries": 2, "retry_interval_hours": 6}
    call_id = fixture["id"]
    respx.get(f"{BASE_URL}calls/{call_id}/").mock(return_value=httpx.Response(200, json=fixture))

    call = await hunar_client.get_call(call_id)

    assert call.retry_config is not None
    assert call.retry_config.max_retries == 2


# -------------------------------------------------------------------------- numbers


@respx.mock
async def test_list_numbers_exposes_allowed_countries(hunar_client: HunarClient) -> None:
    """The org currently has no numbers provisioned (see tests/fixtures/hunar/README.md), so
    this only confirms an empty page parses cleanly. allowed_countries extraction itself is
    covered by test_hunar_preflight.py's check_destination_allowed tests, which build
    PhoneNumber objects directly rather than depending on this fixture."""
    respx.get(f"{BASE_URL}numbers/").mock(
        return_value=httpx.Response(200, json=load_fixture("numbers_list.json"))
    )

    page = await hunar_client.list_numbers()

    assert page.results == []


# --------------------------------------------------------------------- error mapping


@pytest.mark.parametrize(
    ("status", "fixture", "expected"),
    [
        (400, "error_400_telephony.json", HunarTelephonyError),
        (401, "error_401_unauthorized.json", HunarUnauthorized),
        (402, "error_402_quota.json", HunarQuotaExhausted),
        (404, "error_404_not_found.json", HunarNotFound),
        (422, "error_422_validation.json", HunarValidationError),
    ],
)
@respx.mock
async def test_error_statuses_map_to_distinct_exceptions(
    hunar_client: HunarClient, status: int, fixture: str, expected: type[HunarAPIError]
) -> None:
    respx.get(f"{BASE_URL}agents/").mock(
        return_value=httpx.Response(status, json=load_fixture(fixture))
    )

    with pytest.raises(expected) as excinfo:
        await hunar_client.list_agents()

    assert excinfo.value.status_code == status
    assert excinfo.value.message  # the envelope's message survives


@respx.mock
async def test_quota_exhausted_is_surfaceable_to_an_operator(hunar_client: HunarClient) -> None:
    """402 must read as 'calling minutes exhausted', never as a generic failure."""
    respx.post(f"{BASE_URL}calls/").mock(
        return_value=httpx.Response(402, json=load_fixture("error_402_quota.json"))
    )

    with pytest.raises(HunarQuotaExhausted) as excinfo:
        await hunar_client.create_call(
            CallCreate(
                agent_id="agt_1", callee_name="Test Candidate", mobile_number="+919876543210"
            )
        )

    assert excinfo.value.operator_message == "Calling minutes exhausted"
    assert not isinstance(excinfo.value, HunarValidationError)


@respx.mock
async def test_unknown_error_status_falls_back_to_base_error(hunar_client: HunarClient) -> None:
    respx.get(f"{BASE_URL}agents/").mock(return_value=httpx.Response(418, text="teapot"))

    with pytest.raises(HunarAPIError) as excinfo:
        await hunar_client.list_agents()

    assert excinfo.value.status_code == 418
    assert excinfo.value.raw_body == "teapot"


@respx.mock
async def test_non_envelope_error_body_is_preserved_not_invented(
    hunar_client: HunarClient,
) -> None:
    respx.get(f"{BASE_URL}agents/").mock(
        return_value=httpx.Response(404, text="<html>gateway</html>")
    )

    with pytest.raises(HunarNotFound) as excinfo:
        await hunar_client.list_agents()

    assert excinfo.value.message is None  # nothing fabricated
    assert excinfo.value.raw_body == "<html>gateway</html>"


# --------------------------------------------------------------------- retry policy


@respx.mock
async def test_retries_5xx_then_succeeds(hunar_client: HunarClient) -> None:
    route = respx.get(f"{BASE_URL}agents/").mock(
        side_effect=[
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json=load_fixture("agents_list.json")),
        ]
    )

    page = await hunar_client.list_agents()

    assert route.call_count == 2
    assert page.count == 53


@respx.mock
async def test_exhausted_retries_raise_the_underlying_api_error(
    hunar_client: HunarClient,
) -> None:
    route = respx.get(f"{BASE_URL}agents/").mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(HunarAPIError) as excinfo:
        await hunar_client.list_agents()

    assert route.call_count == 2  # max_attempts
    assert excinfo.value.status_code == 500


@respx.mock
async def test_retries_connect_errors(hunar_client: HunarClient) -> None:
    route = respx.get(f"{BASE_URL}agents/").mock(
        side_effect=[
            httpx.ConnectError("refused"),
            httpx.Response(200, json=load_fixture("agents_list.json")),
        ]
    )

    page = await hunar_client.list_agents()

    assert route.call_count == 2
    assert page.count == 53


@respx.mock
async def test_retries_timeouts(hunar_client: HunarClient) -> None:
    route = respx.get(f"{BASE_URL}agents/").mock(
        side_effect=[
            httpx.ReadTimeout("slow"),
            httpx.Response(200, json=load_fixture("agents_list.json")),
        ]
    )

    await hunar_client.list_agents()

    assert route.call_count == 2


@pytest.mark.parametrize("status", [400, 401, 402, 404, 422])
@respx.mock
async def test_never_retries_4xx(hunar_client: HunarClient, status: int) -> None:
    """A 4xx will not become truthy by asking again, and retrying a call creation risks
    duplicate side effects."""
    route = respx.post(f"{BASE_URL}calls/").mock(
        return_value=httpx.Response(status, json={"success": False, "message": "nope"})
    )

    with pytest.raises(HunarAPIError):
        await hunar_client.create_call(
            CallCreate(
                agent_id="agt_1", callee_name="Test Candidate", mobile_number="+919876543210"
            )
        )

    assert route.call_count == 1


# ------------------------------------------------------------------------ misc


async def test_client_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        HunarClient("")


@respx.mock
async def test_injected_client_still_gets_auth_and_absolute_url() -> None:
    """A caller-supplied httpx.AsyncClient must behave identically to one we build. Headers
    and base URL are applied per-request precisely so an injected client cannot end up sending
    unauthenticated requests to a relative path."""
    route = respx.get(f"{BASE_URL}numbers/").mock(
        return_value=httpx.Response(200, json=load_fixture("numbers_list.json"))
    )

    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        client = HunarClient(TEST_API_KEY, client=transport)
        await client.list_numbers()

    request = route.calls.last.request
    assert request.headers["X-API-Key"] == TEST_API_KEY
    assert str(request.url) == f"{BASE_URL}numbers/"


@respx.mock
async def test_client_works_as_async_context_manager() -> None:
    respx.get(f"{BASE_URL}numbers/").mock(
        return_value=httpx.Response(200, json=load_fixture("numbers_list.json"))
    )

    async with HunarClient(TEST_API_KEY) as client:
        page = await client.list_numbers()

    assert page.count == 0
