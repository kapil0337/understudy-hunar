# Understudy

Rehearse-then-dial voice recruiting on the Hunar Voice Agents API. See [CLAUDE.md](CLAUDE.md) for
the project brief and hard rules.

## Layout

```
backend/   FastAPI, Python 3.12, uv
web/       Next.js 15 (App Router), TypeScript strict, Tailwind, shadcn/ui
docs/      design notes, architecture decisions, API reference
```

## Quickstart

```bash
git clone <repo> && cd understudy
make up
```

This boots Postgres, the backend (`http://localhost:8000`, see `/healthz`), and the web app
(`http://localhost:3000`). No `.env` files are required to boot — `docker compose` supplies
`DATABASE_URL` itself, and the optional Hunar/NVIDIA/PDL integrations degrade gracefully when
their keys are absent (`GET /healthz` reports which are enabled). To turn those on, or to run
either app outside Docker, copy `backend/.env.example` to `backend/.env` and
`web/.env.example` to `web/.env.local` and fill in what you have.

## Deployment

`backend/Dockerfile` and `web/Dockerfile` are for local `docker compose` and self-hosting. The
production frontend deploys to **Vercel**, which builds directly from git and does not run
`web/Dockerfile` — that file exists only for the compose setup above and for anyone self-hosting
instead of using Vercel.

## Makefile

| Command        | What it does                                                    |
| -------------- | ---------------------------------------------------------------- |
| `make up`      | Build and start the full stack (Postgres, backend, web)          |
| `make down`    | Stop the stack                                                   |
| `make logs`    | Tail logs from all services                                      |
| `make migrate` | Apply Alembic migrations against the running backend container   |
| `make seed`    | Seed the database from `backend/fixtures/`                       |
| `make test`    | Run the backend test suite against a disposable Postgres         |
| `make gen-api` | Regenerate the web app's TS types from the backend's OpenAPI schema |
| `make fmt`     | Format backend (ruff) and web (prettier)                         |
| `make lint`    | Lint backend (ruff, mypy) and web (eslint)                       |

## CI

`.github/workflows/ci.yml` runs the backend suite (ruff, mypy strict, pytest against a Postgres
service), the web suite (`tsc --noEmit`, eslint, `next build`), and a repo-wide grep for the
Hunar/NVIDIA live key prefixes that fails the build on a hit.

## Pre-commit

```bash
pip install pre-commit  # or: uvx pre-commit ...
pre-commit install
```

Runs ruff, ruff-format, and gitleaks on each commit — see `.pre-commit-config.yaml`.
