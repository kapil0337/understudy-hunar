"""Tests for the fixture-capture scrubber.

This is the component that stands between a live API response and a committed file, so it is
tested directly rather than trusted. A miss here commits a real phone number or key.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capture_hunar_fixtures.py"
_spec = importlib.util.spec_from_file_location("capture_hunar_fixtures", _SCRIPT)
assert _spec is not None and _spec.loader is not None
capture = importlib.util.module_from_spec(_spec)
sys.modules["capture_hunar_fixtures"] = capture
_spec.loader.exec_module(capture)

# Split so CI's repo-wide secret grep (.github/workflows/ci.yml) does not have to special-case
# this file the way it does app/core/logging.py and capture_hunar_fixtures.py — these are test
# inputs for the scrubber, not real keys, but the grep matches on the literal substring alone
# and cannot tell the difference.
_FAKE_LIVE_KEY_PREFIX = "hunar" + "_va_live_sk_"


def scrub(payload: Any, *, kind: str | None = None) -> Any:
    return capture.scrub(payload, capture._IdAllocator(), kind=kind)


def test_drops_secret_keys_entirely() -> None:
    out = scrub({"api_key": _FAKE_LIVE_KEY_PREFIX + "real", "token": "t", "name": "keep"})

    assert "api_key" not in out
    assert "token" not in out
    assert out["name"] == "keep"


def test_replaces_phone_numbers_by_key() -> None:
    out = scrub({"mobile_number": "+919812345678", "phone_number": "+14155552671"})

    assert out["mobile_number"] == capture.PLACEHOLDER_IN
    assert out["phone_number"] == capture.PLACEHOLDER_US


def test_replaces_phone_numbers_embedded_in_free_text() -> None:
    """A number that appears in a message body, not just a known field, must still go."""
    out = scrub({"message": "We called +919812345678 twice."})

    assert "+919812345678" not in out["message"]
    assert capture.PLACEHOLDER_IN in out["message"]


def test_replaces_recording_urls() -> None:
    out = scrub({"recording_url": "https://cdn.real-host.com/a/b/call-123.mp3"})

    assert out["recording_url"] == capture.PLACEHOLDER_RECORDING


def test_replaces_recording_url_found_by_shape() -> None:
    out = scrub({"some_other_field": "https://cdn.real-host.com/x/recording-9.wav"})

    assert out["some_other_field"] == capture.PLACEHOLDER_RECORDING


def test_replaces_person_names() -> None:
    out = scrub({"callee_name": "A Real Person", "full_name": "Someone Else"})

    assert out["callee_name"] == capture.PLACEHOLDER_NAME
    assert out["full_name"] == capture.PLACEHOLDER_NAME


def test_ids_are_stable_and_cross_referenced() -> None:
    """The same real id must map to the same fake id everywhere, or fixtures stop lining up."""
    ids = capture._IdAllocator()
    payload = {
        "results": [
            {"id": "real-agent-1", "agent_id": "real-agent-1"},
            {"id": "real-agent-2", "agent_id": "real-agent-1"},
        ]
    }

    out = capture.scrub(payload, ids, kind="agent")
    first, second = out["results"]

    assert first["id"] == first["agent_id"]
    assert second["agent_id"] == first["id"]
    assert second["id"] != first["id"]
    assert first["id"].startswith("agt_")


def test_nested_structures_are_scrubbed() -> None:
    out = scrub(
        {"results": [{"custom_data": {"mobile_number": "+919812345678"}}]},
        kind="call",
    )

    assert out["results"][0]["custom_data"]["mobile_number"] == capture.PLACEHOLDER_IN


def test_write_fixture_refuses_output_containing_a_live_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Last line of defence: even if scrubbing missed something, writing must abort."""
    monkeypatch.setattr(capture, "FIXTURES", tmp_path)

    with pytest.raises(SystemExit, match="REFUSING"):
        capture.write_fixture("bad.json", {"leaked": _FAKE_LIVE_KEY_PREFIX + "abc123"})

    assert not (tmp_path / "bad.json").exists()


def test_write_fixture_writes_clean_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture, "FIXTURES", tmp_path)

    capture.write_fixture("ok.json", {"id": "agt_1"})

    assert (tmp_path / "ok.json").exists()
