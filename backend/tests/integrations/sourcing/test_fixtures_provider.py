from __future__ import annotations

from app.integrations.sourcing.base import SourcingQuery
from app.integrations.sourcing.fixtures import DEFAULT_FIXTURE_PATH, FixtureProvider


def test_fixture_file_has_forty_candidates() -> None:
    import json

    data = json.loads(DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(data) == 40


def test_fixture_covers_four_cities_and_five_languages() -> None:
    import json

    data = json.loads(DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert {c["location"] for c in data} == {"Chennai", "Bengaluru", "Hyderabad", "Pune"}
    assert {c["preferred_language"] for c in data} == {
        "TAMIL",
        "TELUGU",
        "KANNADA",
        "HINDI",
        "ENGLISH",
    }


async def test_search_never_populates_a_phone_number() -> None:
    provider = FixtureProvider()
    result = await provider.search(SourcingQuery(limit=40))
    assert len(result.candidates) == 40
    for candidate in result.candidates:
        assert candidate.needs_phone is True
        assert not hasattr(candidate, "phone_e164")


async def test_search_filters_by_location() -> None:
    provider = FixtureProvider()
    result = await provider.search(SourcingQuery(locations=["Chennai"], limit=40))
    assert result.candidates
    assert all(c.location == "Chennai" for c in result.candidates)


async def test_search_treats_country_level_location_as_unfiltered() -> None:
    """A compiled JD for a nationwide role can extract locations=["India"] — every fixture
    candidate is already India-based and stored as a bare city name, so a literal substring
    match against "india" would otherwise silently return zero candidates for every such job."""
    provider = FixtureProvider()
    result = await provider.search(SourcingQuery(locations=["India"], limit=40))
    assert len(result.candidates) == 40


async def test_search_filters_by_skill() -> None:
    provider = FixtureProvider()
    result = await provider.search(SourcingQuery(skills=["barcode scanner"], limit=40))
    assert result.candidates
    assert all("barcode scanner" in c.skills for c in result.candidates)


async def test_search_filters_by_title_substring() -> None:
    provider = FixtureProvider()
    result = await provider.search(SourcingQuery(titles=["Delivery Rider"], limit=40))
    assert result.candidates
    assert all(c.current_title == "Delivery Rider" for c in result.candidates)


async def test_search_filters_by_min_years() -> None:
    provider = FixtureProvider()
    result = await provider.search(SourcingQuery(min_years=8, limit=40))
    assert result.candidates
    assert all(
        c.years_experience is not None and c.years_experience >= 8 for c in result.candidates
    )


async def test_search_respects_limit() -> None:
    provider = FixtureProvider()
    result = await provider.search(SourcingQuery(limit=5))
    assert len(result.candidates) == 5


async def test_search_is_deterministic() -> None:
    provider = FixtureProvider()
    first = await provider.search(SourcingQuery(locations=["Pune"], limit=40))
    second = await provider.search(SourcingQuery(locations=["Pune"], limit=40))
    assert [c.source_ref for c in first.candidates] == [c.source_ref for c in second.candidates]


async def test_empty_query_returns_candidates_up_to_default_limit() -> None:
    provider = FixtureProvider()
    result = await provider.search(SourcingQuery())
    assert len(result.candidates) == 10  # SourcingQuery default limit
