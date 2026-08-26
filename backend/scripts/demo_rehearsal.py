#!/usr/bin/env python
"""End-to-end rehearsal demo: compile a fixture JD, rehearse it, propose and accept a patch,
re-rehearse, and print the before/after score delta.

    uv run python scripts/demo_rehearsal.py [fixture_name]

fixture_name defaults to delivery_rider_chennai; see backend/fixtures/jd/ for the others
(retail_associate_bengaluru, warehouse_picker_pune).

Needs DATABASE_URL and at least one of NVIDIA_API_KEY/GEMINI_API_KEY — every LLM call in here is
real. It never touches the real Hunar API: that is the entire point of rehearsing before dialing
(CONTRIBUTING.md). Safe to re-run; each run writes a fresh Job/AgentVersion/RehearsalRun rather than
reusing a previous one (only the compiled-JD cache and any already-generated personas are
reused, both keyed by content).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.logging import configure_logging  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.db.migrate import run_migrations_with_lock  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402
from app.models.enums import Language  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.schemas.rehearsal import RehearsalScore  # noqa: E402
from app.services.jd_compiler import compile_jd, create_initial_version  # noqa: E402
from app.services.personas import get_or_regenerate_personas  # noqa: E402
from app.services.rehearsal.patch import accept_patch, propose_patch, score_delta  # noqa: E402
from app.services.rehearsal.run import run_rehearsal  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "jd"
DEFAULT_FIXTURE = "delivery_rider_chennai"


def _rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _print_breakdown(label: str, score: RehearsalScore) -> None:
    _rule(f"{label} — composite {score.composite:.1f}/100")
    print(f"  extraction_accuracy  {score.extraction_accuracy.score:5.1f}  (weight 40)")
    print(f"  coverage             {score.coverage.score:5.1f}  (weight 25)")
    print(f"  faithfulness         {score.faithfulness.score:5.1f}  (weight 25)")
    print(f"  efficiency           {score.efficiency.score:5.1f}  (weight 10)")
    if not score.failures:
        print("\n  no failures.")
        return
    print(f"\n  {len(score.failures)} failure(s), most severe first:")
    for failure in score.failures[:6]:
        excerpt = f"  ({failure.transcript_excerpt!r})" if failure.transcript_excerpt else ""
        print(f"    [{failure.severity:>8}] {failure.metric}: {failure.description}{excerpt}")


async def main() -> int:
    fixture_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    raw_jd_path = FIXTURE_DIR / f"{fixture_name}.txt"
    if not raw_jd_path.exists():
        available = ", ".join(p.stem for p in sorted(FIXTURE_DIR.glob("*.txt")))
        print(f"No such fixture: {raw_jd_path}\nAvailable: {available}", file=sys.stderr)
        return 2

    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.nvidia_api_key and not settings.gemini_api_key:
        print(
            "Need NVIDIA_API_KEY or GEMINI_API_KEY set — this script makes real LLM calls.",
            file=sys.stderr,
        )
        return 2

    await run_migrations_with_lock(engine)

    async with async_session_factory() as session:
        raw_jd = raw_jd_path.read_text(encoding="utf-8")

        _rule(f"Compiling {fixture_name}")
        compiled = await compile_jd(raw_jd, session=session)
        print(f"  role_title: {compiled.role_title}")
        print(
            f"  {len(compiled.screening_questions)} screening question(s), "
            f"{len(compiled.knockout_criteria)} knockout criterion/criteria"
        )

        job = Job(
            title=compiled.role_title, raw_jd=raw_jd, compiled=compiled.model_dump(mode="json")
        )
        session.add(job)
        await session.flush()

        version = await create_initial_version(session, job.id, compiled, Language.ENGLISH)
        await session.commit()
        print(f"  agent_version v{version.version_no} created ({version.id})")

        _rule("Generating personas")
        personas = await get_or_regenerate_personas(session, job.id, compiled)
        await session.commit()
        for persona in personas:
            print(f"  {persona.archetype:<18} {persona.profile.get('name', '?')}")

        _rule(f"Rehearsing v{version.version_no}")
        run_1 = await run_rehearsal(session, version, compiled, personas)
        if run_1.scores is None:
            print(f"  run failed: {run_1.error}", file=sys.stderr)
            return 1
        score_1 = RehearsalScore.model_validate(run_1.scores)
        _print_breakdown(f"v{version.version_no}", score_1)

        _rule("Proposing a patch")
        patch = await propose_patch(session, run_1, compiled)
        await session.commit()
        print(f"  {len(patch.rationale)} rationale item(s):")
        for item in patch.rationale:
            print(f"    [{item['failure_id']}] {item['change_summary']}")

        _rule("Accepting the patch and re-rehearsing")
        accepted = await accept_patch(session, patch, compiled)
        print(f"  agent_version v{accepted.version.version_no} created ({accepted.version.id})")
        if accepted.run.scores is None:
            print(f"  run failed: {accepted.run.error}", file=sys.stderr)
            return 1
        score_2 = RehearsalScore.model_validate(accepted.run.scores)
        _print_breakdown(f"v{accepted.version.version_no}", score_2)

        _rule(f"Delta: v{version.version_no} -> v{accepted.version.version_no}")
        delta = score_delta(run_1, accepted.run)
        for metric, value in delta.items():
            sign = "+" if value >= 0 else ""
            print(f"  {metric:<20} {sign}{value:.1f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
