"""Hunar webhook signature verification.

Per CLAUDE.md, the signature is a base64 HMAC-SHA256 over:

    f"{X-Hunar-Timestamp}.".encode() + raw_body_bytes

keyed by the API key. The header may carry several comma-separated signatures (key rotation),
and any one of them matching is a pass. Comparison is constant-time, and timestamps outside a
300 second window are rejected so a captured payload cannot be replayed indefinitely.

The body MUST be the raw bytes as received. Re-serialising the parsed JSON will change
whitespace or key order and the signature will not match.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

DEFAULT_MAX_AGE_SECONDS = 300


def compute_webhook_signature(api_key: str, timestamp: str, raw_body: bytes) -> str:
    """Return the expected base64 signature for one payload."""
    message = f"{timestamp}.".encode() + raw_body
    digest = hmac.new(api_key.encode(), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_webhook_signature(
    api_key: str,
    timestamp: str,
    raw_body: bytes,
    signature_header: str,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> bool:
    """Verify a Hunar webhook signature.

    Returns True only if the timestamp is fresh AND at least one signature in the header
    matches. Returns False rather than raising: a bad signature is an expected condition on a
    public endpoint, not an exceptional one, and every rejection is recorded on webhook_event
    with signature_valid=False either way.

    `now` is injectable purely so freshness can be tested deterministically.
    """
    if not api_key or not signature_header or not timestamp:
        return False

    if not _timestamp_is_fresh(timestamp, max_age_seconds=max_age_seconds, now=now):
        return False

    expected = compute_webhook_signature(api_key, timestamp, raw_body)

    # Compare against every candidate; never short-circuit on the first mismatch in a way that
    # leaks position, and never skip the remaining candidates.
    matched = False
    for candidate in signature_header.split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        if hmac.compare_digest(candidate, expected):
            matched = True
    return matched


def _timestamp_is_fresh(timestamp: str, *, max_age_seconds: int, now: float | None = None) -> bool:
    try:
        sent_at = float(timestamp)
    except (TypeError, ValueError):
        return False

    current = time.time() if now is None else now
    # abs() so a clock-skewed future timestamp is rejected too, not just a stale one.
    return abs(current - sent_at) <= max_age_seconds
