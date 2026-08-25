from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from app.integrations.hunar.signature import (
    compute_webhook_signature,
    verify_webhook_signature,
)
from tests.integrations.conftest import load_fixture

API_KEY = "test-key-not-a-real-credential"
TIMESTAMP = "1700000000"
NOW = 1700000000.0  # pinned so freshness checks are deterministic
BODY = b'{"call_id":"cal_1","status":"COMPLETED"}'


def independent_signature(api_key: str, timestamp: str, body: bytes) -> str:
    """Recompute the signature straight from the CLAUDE.md spec, without touching the
    implementation under test. If signature.py drifts from the spec, this disagrees."""
    message = f"{timestamp}.".encode() + body
    return base64.b64encode(
        hmac.new(api_key.encode("utf-8"), message, hashlib.sha256).digest()
    ).decode("ascii")


def test_known_vector_matches_independently_computed_value() -> None:
    """A fixed vector pinned as a literal.

    This value was produced outside Python entirely, so it does not inherit any assumption
    from the implementation under test:

        printf '1700000000.{"call_id":"cal_1","status":"COMPLETED"}' > msg.bin
        openssl dgst -sha256 -hmac "test-key-not-a-real-credential" -binary msg.bin \\
            | openssl base64

    The literal is what makes this a real test: if signature.py and the helper above both
    drifted from the spec in the same way, this hard-coded string would still catch it.
    """
    expected = "vko13yz4P3Tj2l/cJMBlJ3BKU2zb9DkhoGHCMmQOLaA="

    assert independent_signature(API_KEY, TIMESTAMP, BODY) == expected
    assert compute_webhook_signature(API_KEY, TIMESTAMP, BODY) == expected
    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, expected, now=NOW) is True


def test_accepts_valid_signature() -> None:
    signature = independent_signature(API_KEY, TIMESTAMP, BODY)

    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, signature, now=NOW) is True


def test_accepts_comma_separated_multi_signature_header() -> None:
    """Key rotation can produce several comma-separated signatures; any one matching passes."""
    valid = independent_signature(API_KEY, TIMESTAMP, BODY)
    header = f"{independent_signature('old-key', TIMESTAMP, BODY)},{valid}"

    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, header, now=NOW) is True


def test_accepts_multi_signature_header_with_whitespace() -> None:
    valid = independent_signature(API_KEY, TIMESTAMP, BODY)
    header = f"  {independent_signature('other', TIMESTAMP, BODY)} ,  {valid}  "

    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, header, now=NOW) is True


def test_rejects_when_no_signature_in_header_matches() -> None:
    header = ",".join(independent_signature(key, TIMESTAMP, BODY) for key in ("wrong-1", "wrong-2"))

    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, header, now=NOW) is False


def test_rejects_tampered_body() -> None:
    """Signature computed over the original body must not validate a modified one."""
    signature = independent_signature(API_KEY, TIMESTAMP, BODY)
    tampered = BODY.replace(b"COMPLETED", b"FAILED___")

    assert len(tampered) == len(BODY)  # same length, so only content differs
    assert verify_webhook_signature(API_KEY, TIMESTAMP, tampered, signature, now=NOW) is False


def test_rejects_tampered_body_single_byte() -> None:
    signature = independent_signature(API_KEY, TIMESTAMP, BODY)
    tampered = bytearray(BODY)
    tampered[-2] ^= 0x01

    assert (
        verify_webhook_signature(API_KEY, TIMESTAMP, bytes(tampered), signature, now=NOW) is False
    )


def test_rejects_stale_timestamp() -> None:
    """Older than 300s must fail even though the signature itself is cryptographically valid."""
    signature = independent_signature(API_KEY, TIMESTAMP, BODY)
    much_later = NOW + 301

    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, signature, now=much_later) is False


def test_accepts_timestamp_just_inside_window() -> None:
    signature = independent_signature(API_KEY, TIMESTAMP, BODY)

    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, signature, now=NOW + 299) is True


def test_rejects_future_timestamp_beyond_skew() -> None:
    """A far-future timestamp is rejected too — the window is absolute, not one-sided."""
    signature = independent_signature(API_KEY, TIMESTAMP, BODY)

    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, signature, now=NOW - 301) is False


def test_rejects_wrong_key() -> None:
    signature = independent_signature("a-different-key", TIMESTAMP, BODY)

    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, signature, now=NOW) is False


def test_signature_is_bound_to_the_timestamp() -> None:
    """The timestamp is inside the signed message, so reusing a signature under a different
    (still fresh) timestamp must fail."""
    signature = independent_signature(API_KEY, TIMESTAMP, BODY)
    other_timestamp = str(int(TIMESTAMP) + 10)

    assert verify_webhook_signature(API_KEY, other_timestamp, BODY, signature, now=NOW) is False


@pytest.mark.parametrize(
    ("api_key", "timestamp", "header"),
    [
        ("", TIMESTAMP, "sig"),
        (API_KEY, "", "sig"),
        (API_KEY, TIMESTAMP, ""),
        (API_KEY, "not-a-number", "sig"),
    ],
)
def test_rejects_missing_or_malformed_inputs(api_key: str, timestamp: str, header: str) -> None:
    assert verify_webhook_signature(api_key, timestamp, BODY, header, now=NOW) is False


def test_rejects_empty_segments_in_header() -> None:
    assert verify_webhook_signature(API_KEY, TIMESTAMP, BODY, ",,,", now=NOW) is False


@pytest.mark.parametrize(
    "fixture_name",
    [
        "webhook_call_status.json",
        "webhook_call_recording.json",
        "webhook_call_result.json",
        "webhook_call_summary.json",
    ],
)
def test_verifies_real_webhook_payload_shapes(fixture_name: str) -> None:
    """Sign the exact bytes of each webhook fixture and verify them round-trip."""
    raw_body = json.dumps(load_fixture(fixture_name)).encode()
    signature = independent_signature(API_KEY, TIMESTAMP, raw_body)

    assert verify_webhook_signature(API_KEY, TIMESTAMP, raw_body, signature, now=NOW) is True


def test_reserialised_body_does_not_verify() -> None:
    """Guards the documented requirement to use the RAW body: re-serialising the parsed JSON
    changes the bytes, and the signature must then fail rather than silently pass."""
    raw_body = b'{"call_id":"cal_1","status":"COMPLETED"}'
    signature = independent_signature(API_KEY, TIMESTAMP, raw_body)

    reserialised = json.dumps(json.loads(raw_body)).encode()  # adds spaces after ':' and ','

    assert reserialised != raw_body
    assert verify_webhook_signature(API_KEY, TIMESTAMP, reserialised, signature, now=NOW) is False
