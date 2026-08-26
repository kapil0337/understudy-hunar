from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from tenacity import wait_none

from app.integrations.sourcing.base import (
    SourcingAuthError,
    SourcingProviderError,
    SourcingQuery,
    SourcingQuotaExceeded,
)
from app.integrations.sourcing.coresignal import (
    BASE_URL,
    MAX_RESULTS_PER_SEARCH,
    CoresignalProvider,
    CoresignalQuotaExceeded,
    CoresignalUnauthorized,
    build_search_query,
)
from app.integrations.ratelimit import TokenBucket

# Not a real key: exists only so the auth header has something deterministic to check.
TEST_API_KEY = "test-key-not-a-real-credential"
SEARCH_URL = f"{BASE_URL}/employee_multi_source/search/es_dsl"


def _collect_url(employee_id: int) -> str:
    return f"{BASE_URL}/employee_multi_source/collect/{employee_id}"


@pytest.fixture
async def coresignal_provider() -> AsyncIterator[CoresignalProvider]:
    # max_attempts=2 exercises more than one attempt; wait_none drops the backoff. A large,
    # effectively-unlimited rate limiter here — the rate limiter itself has its own test.
    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        provider = CoresignalProvider(
            TEST_API_KEY,
            max_attempts=2,
            retry_wait=wait_none(),
            rate_limiter=TokenBucket(capacity=1000, period_seconds=60),
            client=transport,
        )
        yield provider


# ------------------------------------------------------------------- build_search_query


def test_build_search_query_empty_query_matches_all() -> None:
    body = build_search_query(SourcingQuery())
    assert body == {"query": {"match_all": {}}}


def test_build_search_query_has_no_sibling_keys() -> None:
    # Coresignal's schema rejects any top-level key besides `query` (extra_forbidden) —
    # verified live against the real API. There is deliberately no `size` here.
    body = build_search_query(SourcingQuery(limit=500))
    assert set(body.keys()) == {"query"}


def test_build_search_query_includes_titles_skills_locations_years() -> None:
    query = SourcingQuery(
        titles=["Delivery Rider"],
        skills=["Two-Wheeler Riding"],
        locations=["Chennai"],
        min_years=2,
    )
    must = build_search_query(query)["query"]["bool"]["must"]
    assert {"bool": {"should": [{"match": {"active_experience_title": "Delivery Rider"}}]}} in must
    assert {"bool": {"should": [{"match": {"inferred_skills": "Two-Wheeler Riding"}}]}} in must
    assert {"bool": {"should": [{"match": {"location_full": "Chennai"}}]}} in must
    assert {"range": {"total_experience_duration_months": {"gte": 24}}} in must


# ------------------------------------------------------------------------------ search()


@respx.mock
async def test_search_never_populates_a_phone_number(
    coresignal_provider: CoresignalProvider,
) -> None:
    """The core CLAUDE.md rule for this provider: phone_e164 must never come from Coresignal —
    and unlike PDL, this API has no phone-presence flag of any kind."""
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(200, json=[1, 2]))
    respx.get(_collect_url(1)).mock(
        return_value=httpx.Response(200, json={"id": 1, "full_name": "Test Candidate A"})
    )
    respx.get(_collect_url(2)).mock(
        return_value=httpx.Response(200, json={"id": 2, "full_name": "Test Candidate B"})
    )

    result = await coresignal_provider.search(SourcingQuery())

    assert len(result.candidates) == 2
    for candidate in result.candidates:
        assert candidate.has_phone_flag is False
        assert candidate.needs_phone is True
        assert not hasattr(candidate, "phone_e164")


@respx.mock
async def test_search_parses_result_shape_and_finds_active_experience(
    coresignal_provider: CoresignalProvider,
) -> None:
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(200, json=[168923108]))
    respx.get(_collect_url(168923108)).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 168923108,
                "full_name": "Test Candidate",
                "headline": "Lead Data Scientist @ Acme",
                "active_experience_title": "Lead Data Scientist",
                "location_full": "India",
                "inferred_skills": ["machine learning", "forecasting"],
                "total_experience_duration_months": 81,
                "linkedin_url": "https://www.linkedin.com/in/test-candidate",
                "experience": [
                    {"active_experience": 0, "company_name": "Old Co"},
                    {"active_experience": 1, "company_name": "Acme Inc."},
                ],
            },
        )
    )

    result = await coresignal_provider.search(SourcingQuery())

    assert result.provider == "coresignal"
    candidate = result.candidates[0]
    assert candidate.full_name == "Test Candidate"
    assert candidate.current_title == "Lead Data Scientist"
    assert candidate.current_company == "Acme Inc."  # the active_experience==1 entry, not [0]
    assert candidate.location == "India"
    assert candidate.skills == ["machine learning", "forecasting"]
    assert candidate.years_experience == pytest.approx(81 / 12)
    assert candidate.linkedin_url == "https://www.linkedin.com/in/test-candidate"


@respx.mock
async def test_search_caps_collect_calls_at_max_results(
    coresignal_provider: CoresignalProvider,
) -> None:
    ids = list(range(1, MAX_RESULTS_PER_SEARCH + 5))
    route = respx.post(SEARCH_URL).mock(return_value=httpx.Response(200, json=ids))
    collect_routes = [
        respx.get(_collect_url(i)).mock(
            return_value=httpx.Response(200, json={"id": i, "full_name": f"Candidate {i}"})
        )
        for i in ids
    ]

    result = await coresignal_provider.search(SourcingQuery(limit=500))

    assert route.call_count == 1
    assert len(result.candidates) == MAX_RESULTS_PER_SEARCH
    called = sum(1 for r in collect_routes if r.call_count > 0)
    assert called == MAX_RESULTS_PER_SEARCH


@respx.mock
async def test_search_unexpected_shape_raises_provider_error(
    coresignal_provider: CoresignalProvider,
) -> None:
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(200, json={"unexpected": "shape"}))

    with pytest.raises(SourcingProviderError):
        await coresignal_provider.search(SourcingQuery())


@respx.mock
async def test_401_raises_sourcing_auth_error(coresignal_provider: CoresignalProvider) -> None:
    respx.post(SEARCH_URL).mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized", "request_id": "r1"})
    )

    with pytest.raises(CoresignalUnauthorized) as excinfo:
        await coresignal_provider.search(SourcingQuery())
    assert isinstance(excinfo.value, SourcingAuthError)


@pytest.mark.parametrize("status", [402, 429])
@respx.mock
async def test_quota_statuses_raise_sourcing_quota_exceeded(
    coresignal_provider: CoresignalProvider, status: int
) -> None:
    respx.post(SEARCH_URL).mock(
        return_value=httpx.Response(
            status, json={"message": "API rate limit exceeded", "request_id": "r1"}
        )
    )

    with pytest.raises(CoresignalQuotaExceeded) as excinfo:
        await coresignal_provider.search(SourcingQuery())
    assert isinstance(excinfo.value, SourcingQuotaExceeded)


@respx.mock
async def test_retries_5xx_then_succeeds(coresignal_provider: CoresignalProvider) -> None:
    route = respx.post(SEARCH_URL).mock(
        side_effect=[httpx.Response(503, text="unavailable"), httpx.Response(200, json=[])]
    )

    result = await coresignal_provider.search(SourcingQuery())

    assert route.call_count == 2
    assert result.candidates == []


@respx.mock
async def test_exhausted_retries_raise_provider_error(
    coresignal_provider: CoresignalProvider,
) -> None:
    route = respx.post(SEARCH_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(SourcingProviderError):
        await coresignal_provider.search(SourcingQuery())
    assert route.call_count == 2  # max_attempts


def test_empty_api_key_rejected() -> None:
    with pytest.raises(ValueError):
        CoresignalProvider("")
