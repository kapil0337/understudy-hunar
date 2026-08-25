#!/usr/bin/env python
"""Smoke-test the Hunar connection: print agents, numbers, and allowed_countries per number.

    export HUNAR_API_KEY=...
    uv run python scripts/smoke_hunar.py

Read-only. It never creates an agent or places a call, so it costs no calling minutes.

Exit codes: 0 success, 2 no API key, 1 the API rejected us (the message says how).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.hunar.client import HunarClient  # noqa: E402
from app.integrations.hunar.exceptions import (  # noqa: E402
    HunarAPIError,
    HunarQuotaExhausted,
    HunarUnauthorized,
)


def _rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


async def main() -> int:
    api_key = os.environ.get("HUNAR_API_KEY")
    if not api_key:
        print("HUNAR_API_KEY is not set.", file=sys.stderr)
        return 2

    try:
        async with HunarClient(api_key) as client:
            _rule("Agents")
            agents = await client.list_agents()
            if not agents.results:
                print("(none)")
            for agent in agents.results:
                language = agent.language or "?"
                persona = agent.voice_persona or "?"
                print(f"  {agent.id}  {agent.name}")
                print(f"      language={language}  voice_persona={persona}")
                if agent.custom_variables:
                    print(f"      custom_variables={', '.join(agent.custom_variables)}")

            _rule("Numbers")
            numbers = await client.list_numbers()
            if not numbers.results:
                print("(none)")
            for number in numbers.results:
                label = number.phone_number or "(number withheld)"
                active = "" if number.is_active is None else f"  active={number.is_active}"
                print(f"  {number.id}  {label}  country={number.country or '?'}{active}")
                allowed = ", ".join(number.allowed_countries) or "(none reported)"
                print(f"      allowed_countries: {allowed}")

            print(f"\nOK - {len(agents.results)} agent(s), {len(numbers.results)} number(s).")
            return 0

    except HunarUnauthorized as exc:
        print(f"\nAuth failed: {exc.operator_message}", file=sys.stderr)
        return 1
    except HunarQuotaExhausted as exc:
        # Surfaced explicitly rather than as a generic failure — see exceptions.py.
        print(f"\n{exc.operator_message}", file=sys.stderr)
        return 1
    except HunarAPIError as exc:
        print(
            f"\nHunar API error (HTTP {exc.status_code}): {exc.operator_message}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
