from __future__ import annotations

import httpx
import pytest
import respx

from app.integrations.sourcing.base import (
    SourcingAuthError,
    SourcingProviderError,
    SourcingQuery,
    SourcingQuotaExceeded,
)
from app.integrations.sourcing.exceptions import PDLQuotaExceeded, PDLUnauthorized
from app.integrations.sourcing.pdl import MAX_RESULTS_PER_SEARCH, PDLProvider, build_search_body
from tests.integrations.sourcing.conftest import BASE_URL

# ------------------------------------------------------------------- build_search_body


def test_build_search_body_caps_limit_at_ten() -> None:
    body = build_search_body(SourcingQuery(limit=500))
    assert body["size"] == MAX_RESULTS_PER_SEARCH


def test_build_search_body_respects_smaller_limit() -> None:
    body = build_search_body(SourcingQuery(limit=3))
    assert body["size"] == 3


def test_build_search_body_empty_query_matches_all() -> None:
    body = build_search_body(SourcingQuery())
    assert body["query"] == {"match_all": {}}


def test_build_search_body_includes_titles_skills_locations() -> None:
    query = SourcingQuery(
        titles=["Delivery Rider"], skills=["Two-Wheeler Riding"], locations=["Chennai"]
    )
    body = build_search_body(query)
    must = body["query"]["bool"]["must"]
    assert {"terms": {"job_title": ["delivery rider"]}} in must
    assert {"terms": {"skills": ["two-wheeler riding"]}} in must
    assert {"terms": {"location_locality": ["chennai"]}} in must


# ------------------------------------------------------------------------------ search()


@respx.mock
async def test_search_never_populates_a_phone_number(pdl_provider: PDLProvider) -> None:
    """The core CLAUDE.md rule for this provider: phone_e164 must never come from PDL, on
    either shape the free tier can return for phone_numbers."""
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": [
                    {
                        "id": "p1",
                        "full_name": "Test Candidate A",
                        "job_title": "Delivery Rider",
                        "phone_numbers": True,  # free-tier boolean flag
                    },
                    {
                        "id": "p2",
                        "full_name": "Test Candidate B",
                        "job_title": "Delivery Rider",
                        "phone_numbers": False,
                    },
                ],
            },
        )
    )

    result = await pdl_provider.search(SourcingQuery(titles=["Delivery Rider"]))

    assert len(result.candidates) == 2
    a, b = result.candidates
    assert a.has_phone_flag is True
    assert b.has_phone_flag is False
    for candidate in result.candidates:
        assert candidate.needs_phone is True
        assert not hasattr(candidate, "phone_e164")


@respx.mock
async def test_search_parses_result_shape(pdl_provider: PDLProvider) -> None:
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": [
                    {
                        "id": "p1",
                        "full_name": "Test Candidate",
                        "job_title": "Retail Sales Associate",
                        "job_company_name": "CityMart Retail",
                        "location_name": "Bengaluru",
                        "skills": ["customer service", "billing"],
                        "linkedin_url": "https://linkedin.com/in/test-candidate",
                        "phone_numbers": False,
                    }
                ],
            },
        )
    )

    result = await pdl_provider.search(SourcingQuery())

    assert result.provider == "pdl"
    candidate = result.candidates[0]
    assert candidate.full_name == "Test Candidate"
    assert candidate.headline == "Retail Sales Associate at CityMart Retail"
    assert candidate.current_company == "CityMart Retail"
    assert candidate.location == "Bengaluru"
    assert candidate.skills == ["customer service", "billing"]


@respx.mock
async def test_401_raises_sourcing_auth_error(pdl_provider: PDLProvider) -> None:
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid key"}})
    )

    with pytest.raises(PDLUnauthorized) as excinfo:
        await pdl_provider.search(SourcingQuery())
    assert isinstance(excinfo.value, SourcingAuthError)


@pytest.mark.parametrize("status", [402, 429])
@respx.mock
async def test_quota_statuses_raise_sourcing_quota_exceeded(
    pdl_provider: PDLProvider, status: int
) -> None:
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(status, json={"error": {"message": "quota"}})
    )

    with pytest.raises(PDLQuotaExceeded) as excinfo:
        await pdl_provider.search(SourcingQuery())
    assert isinstance(excinfo.value, SourcingQuotaExceeded)


@respx.mock
async def test_retries_5xx_then_succeeds(pdl_provider: PDLProvider) -> None:
    route = respx.post(BASE_URL).mock(
        side_effect=[
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json={"status": 200, "data": []}),
        ]
    )

    result = await pdl_provider.search(SourcingQuery())

    assert route.call_count == 2
    assert result.candidates == []


@respx.mock
async def test_exhausted_retries_raise_provider_error(pdl_provider: PDLProvider) -> None:
    route = respx.post(BASE_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(SourcingProviderError):
        await pdl_provider.search(SourcingQuery())
    assert route.call_count == 2  # max_attempts


def test_empty_api_key_rejected() -> None:
    with pytest.raises(ValueError):
        PDLProvider("")
