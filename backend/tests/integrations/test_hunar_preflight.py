from __future__ import annotations

import pytest

from app.integrations.hunar.models import Agent, Guardrails, PhoneNumber, RetryConfig
from app.integrations.hunar.preflight import (
    PreflightError,
    check_custom_data,
    check_destination_allowed,
    check_guardrails,
    check_mobile_number,
    check_retry_config,
)

IN_NUMBER = "+919876543210"
US_NUMBER = "+12025550123"
GB_NUMBER = "+442071838750"


def agent_with(custom_variables: list[str]) -> Agent:
    return Agent(id="agt_1", name="Screener", custom_variables=custom_variables)


def number_allowing(*countries: str) -> PhoneNumber:
    return PhoneNumber(
        id="num_1", phone_number=IN_NUMBER, country="IN", allowed_countries=list(countries)
    )


# ------------------------------------------------------------------- custom_data


def test_custom_data_accepts_exact_cover() -> None:
    agent = agent_with(["candidate_name", "role_title"])

    check_custom_data(agent, {"candidate_name": "A", "role_title": "B"})


def test_custom_data_accepts_superset() -> None:
    """Extra keys are the agent's problem, not a 422 — only missing keys are rejected."""
    agent = agent_with(["candidate_name"])

    check_custom_data(agent, {"candidate_name": "A", "unused": "B"})


def test_custom_data_rejects_missing_key() -> None:
    agent = agent_with(["candidate_name", "role_title"])

    with pytest.raises(PreflightError, match="role_title"):
        check_custom_data(agent, {"candidate_name": "A"})


def test_custom_data_error_names_every_missing_key() -> None:
    agent = agent_with(["a", "b", "c"])

    with pytest.raises(PreflightError) as excinfo:
        check_custom_data(agent, {})

    message = str(excinfo.value)
    assert "a" in message and "b" in message and "c" in message


def test_custom_data_ignored_when_agent_declares_none() -> None:
    check_custom_data(agent_with([]), {})


# ------------------------------------------------------------------ retry_config


def test_retry_config_absent_is_allowed() -> None:
    check_retry_config(None)


@pytest.mark.parametrize("interval", [0, 3, 6, 9, 12, 24])
def test_retry_config_accepts_documented_intervals(interval: int) -> None:
    check_retry_config(RetryConfig(max_retry_count=2, retry_interval_hours=interval))


@pytest.mark.parametrize("count", [0, 5, 10])
def test_retry_config_accepts_valid_counts(count: int) -> None:
    check_retry_config(RetryConfig(max_retry_count=count, retry_interval_hours=6))


@pytest.mark.parametrize("count", [-1, 11, 99])
def test_retry_config_rejects_out_of_range_count(count: int) -> None:
    config = RetryConfig.model_construct(max_retry_count=count, retry_interval_hours=6)

    with pytest.raises(PreflightError, match="max_retry_count"):
        check_retry_config(config)


@pytest.mark.parametrize("interval", [1, 2, 5, 13, 48])
def test_retry_config_rejects_undocumented_interval(interval: int) -> None:
    config = RetryConfig.model_construct(max_retry_count=2, retry_interval_hours=interval)  # type: ignore[arg-type]

    with pytest.raises(PreflightError, match="retry_interval_hours"):
        check_retry_config(config)


def test_retry_config_model_rejects_bad_interval_at_construction() -> None:
    """The Literal type is the first line of defence; preflight is the second."""
    with pytest.raises(ValueError):
        RetryConfig(max_retry_count=2, retry_interval_hours=5)


# -------------------------------------------------------------------- guardrails


def test_guardrails_absent_is_allowed() -> None:
    """Omitting guardrails inherits org defaults — that is valid, not incomplete."""
    check_guardrails(None)


def test_guardrails_accepts_three_days_and_three_hour_window() -> None:
    check_guardrails(
        Guardrails(
            allowed_days=["MON", "TUE", "WED"],
            earliest_call_time="10:00",
            last_call_time="13:00",
        )
    )


def test_guardrails_rejects_two_distinct_days() -> None:
    with pytest.raises(PreflightError, match="3 distinct days"):
        check_guardrails(
            Guardrails(
                allowed_days=["MON", "TUE"],
                earliest_call_time="10:00",
                last_call_time="18:00",
            )
        )


def test_guardrails_counts_distinct_days_not_repeats() -> None:
    """Three entries that are really one day must not satisfy the minimum."""
    with pytest.raises(PreflightError, match="3 distinct days"):
        check_guardrails(
            Guardrails(
                allowed_days=["MON", "MON", "MON"],
                earliest_call_time="10:00",
                last_call_time="18:00",
            )
        )


def test_guardrails_rejects_window_under_three_hours() -> None:
    with pytest.raises(PreflightError, match="at least 3 hours"):
        check_guardrails(
            Guardrails(
                allowed_days=["MON", "TUE", "WED"],
                earliest_call_time="10:00",
                last_call_time="12:59",
            )
        )


def test_guardrails_rejects_inverted_window() -> None:
    with pytest.raises(PreflightError, match="at least 3 hours"):
        check_guardrails(
            Guardrails(
                allowed_days=["MON", "TUE", "WED"],
                earliest_call_time="18:00",
                last_call_time="09:00",
            )
        )


@pytest.mark.parametrize("bad_time", ["25:00", "10:60", "abc", "1000"])
def test_guardrails_model_rejects_malformed_time(bad_time: str) -> None:
    with pytest.raises(ValueError):
        Guardrails(
            allowed_days=["MON", "TUE", "WED"],
            earliest_call_time=bad_time,
            last_call_time="18:00",
        )


# ----------------------------------------------------------------- mobile_number


@pytest.mark.parametrize("number", [IN_NUMBER, US_NUMBER, GB_NUMBER])
def test_mobile_number_accepts_valid_e164(number: str) -> None:
    assert check_mobile_number(number) is not None


def test_mobile_number_requires_plus_prefix() -> None:
    with pytest.raises(PreflightError, match="E.164"):
        check_mobile_number("919876543210")


@pytest.mark.parametrize("number", ["+", "+0", "+99", "not-a-number"])
def test_mobile_number_rejects_unparseable(number: str) -> None:
    with pytest.raises(PreflightError):
        check_mobile_number(number)


def test_mobile_number_rejects_well_formed_but_invalid() -> None:
    """Parses structurally but is not a real allocatable number."""
    with pytest.raises(PreflightError, match="not a valid"):
        check_mobile_number("+11111111111")


# ---------------------------------------------------------- destination allowed


def test_destination_allowed_when_country_listed() -> None:
    check_destination_allowed(IN_NUMBER, number_allowing("IN", "AE"))


def test_destination_allowed_is_case_insensitive() -> None:
    check_destination_allowed(IN_NUMBER, number_allowing("in"))


def test_destination_rejected_when_not_listed() -> None:
    with pytest.raises(PreflightError, match="not in the allowed_countries"):
        check_destination_allowed(US_NUMBER, number_allowing("IN", "AE"))


def test_destination_rejected_when_number_reports_no_allowed_countries() -> None:
    """Refuse rather than assume permission — an empty list is not 'anywhere'."""
    with pytest.raises(PreflightError, match="no allowed_countries"):
        check_destination_allowed(IN_NUMBER, number_allowing())


def test_destination_check_also_validates_the_number() -> None:
    with pytest.raises(PreflightError):
        check_destination_allowed("nonsense", number_allowing("IN"))
