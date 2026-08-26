# backend

FastAPI + Python 3.12 service for Understudy, managed with [uv](https://docs.astral.sh/uv/).

## Local development

```bash
uv sync
cp .env.example .env   # fill in DATABASE_URL at minimum
uv run uvicorn app.main:app --reload
```

Or via the monorepo's `docker compose` setup — see the [root README](../README.md).

## Commands

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy app alembic tests scripts  # type check (strict)
uv run pytest                # tests
uv run alembic upgrade head  # apply migrations
uv run python scripts/seed.py  # idempotent demo seed — see scripts/seed.py's docstring
```

## Layout

- `app/core/` — settings, structlog config, exception handlers
- `app/db/` — SQLAlchemy async engine/session
- `app/models/`, `app/schemas/` — ORM models, Pydantic schemas
- `app/api/` — route handlers (thin — logic lives in `app/services/`)
- `app/integrations/` — adapters for external HTTP APIs (Hunar, NVIDIA, PDL), one per service
- `alembic/` — migrations
- `fixtures/` — test/seed data — no real keys, numbers, or PII, ever (see `fixtures/README.md`)
- `scripts/` — one-off/dev scripts: `seed.py` (demo data), `demo_rehearsal.py` (real LLM calls),
  `smoke_hunar.py` / `capture_hunar_fixtures.py` (real Hunar calls), `replay_webhook.py`

See [CLAUDE.md](../CLAUDE.md) at the repo root for the project brief and hard rules.
