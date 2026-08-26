from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.integrations.hunar.models import (
    Agent,
    AgentCreate,
    Call,
    CallRecordingWebhook,
    CallResultWebhook,
    CallStatusWebhook,
    CallSummaryWebhook,
    HunarError,
    Paginated,
    PhoneNumber,
)
from tests.integrations.conftest import load_fixture


def test_paginated_parses_results_key() -> None:
    page = Paginated[Agent].model_validate(load_fixture("agents_list.json"))

    assert page.count == 53
    assert len(page.results) == 20


@pytest.mark.parametrize("key", ["results", "data", "items"])
def test_paginated_accepts_known_list_aliases(key: str) -> None:
    """The envelope key is not pinned down in CLAUDE.md; silently returning [] because we
    guessed wrong would be a hard bug to spot."""
    agent = load_fixture("agent_detail.json")

    page = Paginated[Agent].model_validate({key: [agent], "count": 1})

    assert len(page.results) == 1


def test_response_models_keep_unknown_fields() -> None:
    """Never drop what Hunar sent just because it is not modelled yet."""
    agent = Agent.model_validate({"id": "agt_1", "name": "x", "an_undocumented_field": "keep me"})

    assert agent.model_extra is not None
    assert agent.model_extra["an_undocumented_field"] == "keep me"


def test_request_models_reject_unknown_fields() -> None:
    """A typo in an outbound payload should fail locally, not as a remote 422."""
    with pytest.raises(ValidationError):
        AgentCreate(
            name="a",
            language="ENGLISH",
            voice_persona="NEHA",
            agent_prompt="p",
            objective="o",
            introduction="i",
            result_prompt="r",
            result_schema={},
            voice_persona_typo="NEHA",  # type: ignore[call-arg]
        )


@pytest.mark.parametrize("bad_language", ["FRENCH", "english", "", "EN"])
def test_language_literal_rejects_undocumented_values(bad_language: str) -> None:
    with pytest.raises(ValidationError):
        AgentCreate(
            name="a",
            language=bad_language,
            voice_persona="NEHA",
            agent_prompt="p",
            objective="o",
            introduction="i",
            result_prompt="r",
            result_schema={},
        )


@pytest.mark.parametrize("bad_persona", ["ALICE", "neha", ""])
def test_voice_persona_literal_rejects_undocumented_values(bad_persona: str) -> None:
    with pytest.raises(ValidationError):
        AgentCreate(
            name="a",
            language="ENGLISH",
            voice_persona=bad_persona,
            agent_prompt="p",
            objective="o",
            introduction="i",
            result_prompt="r",
            result_schema={},
        )


def test_call_status_literal_rejects_undocumented_value() -> None:
    with pytest.raises(ValidationError):
        Call.model_validate({"id": "cal_1", "status": "PENDING"})


def test_call_parses_every_documented_status() -> None:
    for status in (
        "NOT_STARTED",
        "SCHEDULED",
        "INITIATED",
        "RINGING",
        "IN_PROGRESS",
        "COMPLETED",
        "NOT_CONNECTED",
        "CANCELLED",
        "FAILED",
    ):
        assert Call.model_validate({"id": "cal_1", "status": status}).status == status


def test_hunar_error_envelope() -> None:
    error = HunarError.model_validate(load_fixture("error_422_validation.json"))

    assert error.success is False
    assert error.message == "custom_data is missing required keys."
    assert error.details == {"custom_data": ["role_title"]}


def test_phone_number_defaults_allowed_countries_to_empty_list() -> None:
    number = PhoneNumber.model_validate({"id": "num_1"})

    assert number.allowed_countries == []


# ------------------------------------------------------------------- webhooks


def test_call_status_webhook() -> None:
    payload = CallStatusWebhook.model_validate(load_fixture("webhook_call_status.json"))

    assert payload.call_id == "cal_00000000000000000000000001"
    assert payload.status == "IN_PROGRESS"
    assert payload.answered_by == "HUMAN"
    assert payload.request_id == "job1234-cand5678-a1"


def test_call_recording_webhook() -> None:
    payload = CallRecordingWebhook.model_validate(load_fixture("webhook_call_recording.json"))

    assert payload.recording_url is not None
    assert payload.duration_seconds == 143


def test_call_result_webhook_keeps_schema_shaped_result() -> None:
    payload = CallResultWebhook.model_validate(load_fixture("webhook_call_result.json"))

    assert payload.result == {
        "interested": True,
        "notice_period_days": 30,
        "expected_ctc": "18 LPA",
    }


def test_call_summary_webhook() -> None:
    payload = CallSummaryWebhook.model_validate(load_fixture("webhook_call_summary.json"))

    assert payload.summary is not None
    assert "interested" in payload.summary.lower()


def test_webhooks_tolerate_missing_optional_fields() -> None:
    """Webhook delivery is not something we control; a sparse payload must not explode."""
    assert CallStatusWebhook.model_validate({}).call_id is None
    assert CallResultWebhook.model_validate({"call_id": "c"}).result is None
