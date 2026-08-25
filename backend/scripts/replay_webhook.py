#!/usr/bin/env python
"""Sign a captured (or hand-built) Hunar webhook payload and POST it to a locally running
instance — the fastest way to exercise webhook handling without waiting for a real call to
complete.

    uv run python scripts/replay_webhook.py status tests/fixtures/hunar/webhook_call_status.json
    uv run python scripts/replay_webhook.py recording path/to/payload.json --url http://localhost:8000

Needs HUNAR_API_KEY set to the SAME key the target server is configured with (or pass
--api-key). The signature is computed with it, so a mismatched key looks identical to
verify_webhook_signature as no key at all — an invalid signature, correctly rejected with 401,
not a bug in this script.

Exit codes: 0 the server accepted it (2xx), 1 it did not, 2 bad input (no key, bad payload file).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.integrations.hunar.signature import compute_webhook_signature  # noqa: E402

DEFAULT_BASE_URL = "http://localhost:8000"
KINDS = ("status", "recording", "result", "summary")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=KINDS, help="which webhook endpoint to hit")
    parser.add_argument("payload", type=Path, help="path to a JSON payload file")
    parser.add_argument(
        "--url", default=DEFAULT_BASE_URL, help=f"base URL (default {DEFAULT_BASE_URL})"
    )
    parser.add_argument("--api-key", default=None, help="overrides HUNAR_API_KEY")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    api_key = args.api_key or os.environ.get("HUNAR_API_KEY")
    if not api_key:
        print("HUNAR_API_KEY is not set (and --api-key was not given).", file=sys.stderr)
        return 2

    if not args.payload.exists():
        print(f"No such payload file: {args.payload}", file=sys.stderr)
        return 2

    raw_body = args.payload.read_bytes()
    try:
        json.loads(raw_body)
    except ValueError as exc:
        print(f"{args.payload} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    timestamp = str(int(time.time()))
    signature = compute_webhook_signature(api_key, timestamp, raw_body)
    url = f"{args.url.rstrip('/')}/webhooks/hunar/{args.kind}"

    response = httpx.post(
        url,
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hunar-Timestamp": timestamp,
            "X-Hunar-Signature": signature,
        },
    )
    print(f"POST {url} -> {response.status_code}")
    print(response.text)
    return 0 if response.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
