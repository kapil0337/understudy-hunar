#!/usr/bin/env python
"""Capture real Hunar API responses as scrubbed test fixtures.

Run this WHILE THE API KEY IS STILL VALID. The fixtures it writes are what keep the test suite
runnable after the key expires.

    export HUNAR_API_KEY=...
    uv run python scripts/capture_hunar_fixtures.py

Read-only: it calls GET /agents/, GET /calls/ and GET /numbers/ only. It never creates an agent
or places a call, so it costs no calling minutes and has no side effects.

Every response is scrubbed before it touches disk — API keys, phone numbers, recording URLs and
person names are replaced with the placeholders documented in tests/fixtures/hunar/README.md.
The scrubber runs on the parsed structure, and a final scan over the serialised text refuses to
write anything that still looks like a secret.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.hunar.client import HunarClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "hunar"

PLACEHOLDER_IN = "+919876543210"
PLACEHOLDER_US = "+12025550123"
PLACEHOLDER_RECORDING = "https://recordings.example.invalid/scrubbed/rec_0001.mp3"
PLACEHOLDER_NAME = "Test Candidate"
# A call's `result` is free text a real agent generated about a real candidate — it can name
# them, quote their salary, summarise what they said, none of which is caught by scrubbing known
# key names. Every string value under `result` is replaced wholesale rather than pattern-matched
# for names, since "looks like a name" is not reliably detectable and the fixture only needs the
# key/type shape to exercise result: dict[str, Any] parsing, not the real prose.
PLACEHOLDER_RESULT_TEXT = "[scrubbed]"
# Hunar's own sentinel for "not asked/answered this call" — not candidate-derived, safe to keep
# so tests can assert on it.
_RESULT_SENTINEL = "NOT AVAILABLE"

# Keys whose values are replaced wholesale, by key name, wherever they appear.
_SECRET_KEYS = {"api_key", "apikey", "x-api-key", "token", "authorization", "secret"}
_NAME_KEYS = {"callee_name", "candidate_name", "full_name", "name_of_candidate"}
_RECORDING_KEYS = {"recording_url", "recording", "audio_url"}
_PHONE_KEYS = {"mobile_number", "phone_number", "phone", "to_number", "from_number", "caller_id"}

# Stable, non-identifying ids so diffs stay readable across captures.
_ID_PREFIXES = {"agent": "agt_", "call": "cal_", "number": "num_"}

_E164_RE = re.compile(r"\+\d{7,15}")
_URL_RE = re.compile(r"https?://[^\s\"']+")

# Anything matching these in the final text aborts the write.
_FORBIDDEN = [
    re.compile(r"hunar_va_live_sk_"),
    re.compile(r"nvapi-"),
]


class _IdAllocator:
    """Assigns each distinct real id a stable fake one, so cross-references between fixtures
    still line up after scrubbing."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._seen: dict[str, str] = {}

    def fake_for(self, kind: str, real: str) -> str:
        if real in self._seen:
            return self._seen[real]
        self._counters[kind] = self._counters.get(kind, 0) + 1
        fake = f"{_ID_PREFIXES[kind]}{self._counters[kind]:026d}"
        self._seen[real] = fake
        return fake


def _scrub_phone(value: str) -> str:
    return PLACEHOLDER_US if value.startswith("+1") else PLACEHOLDER_IN


def scrub(
    value: Any, ids: _IdAllocator, *, kind: str | None = None, in_result: bool = False
) -> Any:
    """Recursively replace anything sensitive. Structure and key names are preserved so the
    fixture still exercises the real parsing path."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            nested_in_result = in_result or lowered == "result"
            if lowered in _SECRET_KEYS:
                continue  # drop entirely rather than placeholder it
            elif lowered in _PHONE_KEYS and isinstance(item, str):
                out[key] = _scrub_phone(item)
            elif lowered in _RECORDING_KEYS and isinstance(item, str):
                out[key] = PLACEHOLDER_RECORDING
            elif lowered in _NAME_KEYS and isinstance(item, str):
                out[key] = PLACEHOLDER_NAME
            elif lowered == "id" and kind is not None and isinstance(item, str):
                out[key] = ids.fake_for(kind, item)
            elif lowered == "agent_id" and isinstance(item, str):
                out[key] = ids.fake_for("agent", item)
            elif lowered == "call_id" and isinstance(item, str):
                out[key] = ids.fake_for("call", item)
            elif in_result and isinstance(item, str) and item != _RESULT_SENTINEL:
                out[key] = PLACEHOLDER_RESULT_TEXT
            else:
                out[key] = scrub(item, ids, kind=kind, in_result=nested_in_result)
        return out

    if isinstance(value, list):
        return [scrub(item, ids, kind=kind, in_result=in_result) for item in value]

    if isinstance(value, str):
        # Catch anything phone- or URL-shaped that the key-name rules missed.
        value = _E164_RE.sub(lambda m: _scrub_phone(m.group()), value)
        if _URL_RE.match(value) and any(
            token in value.lower() for token in ("record", ".mp3", ".wav", "audio")
        ):
            return PLACEHOLDER_RECORDING
        return value

    return value


def write_fixture(name: str, payload: Any) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n"

    for pattern in _FORBIDDEN:
        if pattern.search(text):
            raise SystemExit(
                f"REFUSING to write {name}: output still matches {pattern.pattern!r}. "
                "Fix the scrubber before retrying."
            )

    path = FIXTURES / name
    path.write_text(text, encoding="utf-8")
    print(f"  wrote {path.relative_to(FIXTURES.parents[2])}")


async def main() -> int:
    api_key = os.environ.get("HUNAR_API_KEY")
    if not api_key:
        print(
            "HUNAR_API_KEY is not set.\n"
            "This script must run while the key is still valid - that is its whole purpose.",
            file=sys.stderr,
        )
        return 2

    FIXTURES.mkdir(parents=True, exist_ok=True)
    ids = _IdAllocator()

    async with HunarClient(api_key) as client:
        print("GET /agents/ ...")
        agents = await client.list_agents()
        write_fixture("agents_list.json", scrub(agents.model_dump(mode="json"), ids, kind="agent"))

        if agents.results:
            first = agents.results[0].id
            print(f"GET /agents/{{id}} ... ({len(agents.results)} agent(s) available)")
            detail = await client.get_agent(first)
            write_fixture(
                "agent_detail.json", scrub(detail.model_dump(mode="json"), ids, kind="agent")
            )
        else:
            print("  no agents returned - skipping agent_detail.json")

        print("GET /calls/ ...")
        calls = await client.list_calls()
        write_fixture("calls_list.json", scrub(calls.model_dump(mode="json"), ids, kind="call"))

        if calls.results:
            detail_call = await client.get_call(calls.results[0].id)
            write_fixture(
                "call_detail.json", scrub(detail_call.model_dump(mode="json"), ids, kind="call")
            )
        else:
            print("  no calls returned - skipping call_detail.json")

        print("GET /numbers/ ...")
        numbers = await client.list_numbers()
        write_fixture(
            "numbers_list.json", scrub(numbers.model_dump(mode="json"), ids, kind="number")
        )

    print(
        "\nDone. Review the diff before committing - a shape that differs from the previous "
        "fixture is a finding about the adapter, not a fixture problem.\n"
        "Then update the 'Status' section of tests/fixtures/hunar/README.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
