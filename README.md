# Understudy

Rehearse-then-dial voice recruiting on the Hunar Voice Agents API.

## Overview

Frontline hiring — delivery riders, warehouse pickers, retail associates — runs on phone screens,
not resumes: someone calls the candidate, asks a fixed set of questions, and decides who moves
forward. Voice AI agents can now make that call instead of a recruiter, but handing a role's
screen straight to an LLM-driven agent is risky: a bad prompt can skip a required question,
misstate something about the job, or run long enough that candidates hang up — and normally you
only find out after it has already called someone.

Understudy adds a rehearsal step in between. A job description compiles into a voice agent's exact
prompt and result schema. That agent is then run against six synthetic candidate personas and
scored on four independent, mostly-deterministic metrics — before it is ever allowed to dial a
real person. If rehearsal finds a problem, a patch is proposed and the fix is measured by
re-rehearsing, never just assumed to have worked. Only a version that scores well gets published
to Hunar and used for real, consented outbound calls.

**Live demo:** `TODO — deploy backend to Render (render.yaml) and frontend to Vercel, then link
both here.` **2-minute walkthrough:** `TODO — record and link here.` Neither is live yet; see
[Setup](#setup) to run it locally in the meantime, or `make seed` for real, no-key data to click
through once it's running.

## Tech stack

- **Backend** — FastAPI, Python 3.12, PostgreSQL (SQLAlchemy async + Alembic), managed with `uv`
- **Frontend** — Next.js 15 (App Router), TypeScript (strict), Tailwind, shadcn/ui
- **LLM** — NVIDIA / Gemini behind one caching adapter (`app/services/llm.py`), keyed by
  `sha256(role, model, messages, schema)` so re-running a rehearsal costs nothing
- **Voice** — Hunar Voice Agents API: agent create/publish, outbound calls, signed webhooks
- **Infra** — Docker Compose locally; Render (backend) + Vercel (frontend) for deploy
- **Tests** — 562 backend tests (pytest, 34 modules) · 25 frontend tests (vitest, 5 suites) · 1
  Playwright E2E spec · gitleaks pre-commit + CI secret scanning

## Assignment coverage

| Assignment item | Where |
| --- | --- |
| 1 — Rehearsal + call screening design, and the outreach channel design | `/jobs/[id]/rehearsal`, `/jobs/[id]/board` screens; [docs/channel-strategy.md](docs/channel-strategy.md) |
| 2 — The application | The whole app: compile → rehearse → source → call → board, `backend/` + `web/` |
| 3 — Attendance without apps | [docs/attendance-without-apps.md](docs/attendance-without-apps.md) |

## How it works

```mermaid
flowchart LR
    JD["Raw job description"] -->|compile, LLM| CJD["Compiled JD"]
    CJD -->|build prompt| V1["Agent version v1"]
    V1 -->|rehearse| P["6 personas, same set every version"]
    P --> SC["Score: 4 metrics -> composite"]
    SC -->|failures found| PATCH["Propose patch"]
    PATCH -->|accept| V2["Agent version v2"]
    V2 -. rehearse again, measure delta .-> SC
    SC -->|scores well| PUB["Publish to Hunar"]
    PUB -->|consented number only| CALL["Real candidate call"]
    CALL --> BOARD["Board + answers"]
```

## The four metrics

A composite score is never shown without these four — see `app/services/rehearsal/score.py`.

- **Extraction accuracy** (40%, deterministic) — extracted result vs. each persona's ground
  truth, field by field.
- **Coverage** (25%, judged) — did the agent actually ask every required question, from its own
  turns only (the candidate's answers are withheld from this judge on purpose).
- **Faithfulness** (25%, judged) — did the agent state anything about the role beyond the
  compiled JD's approved fact list.
- **Efficiency** (10%, deterministic) — call length against a 90-second target.

Two of the four never touch a model. Extraction accuracy and efficiency are plain functions of
the transcript and the ground truth — computing them in Python means they can't drift, can't be
gamed by a differently-worded prompt, and reproduce identically on every run. Coverage and
faithfulness genuinely need judgment (did this phrasing count as asking the question; is this
claim inside or outside the approved fact list), which is why those two stay judged rather than
also being forced into a keyword match that would silently miss paraphrases.

## Design decisions

- **Agent versions are immutable, never edited in place.** A rehearsal score always refers to an
  exact, retrievable prompt — v1 stays v1 forever, even after a patch produces v2. The tradeoff is
  more rows, not fewer: every accepted patch is a new version, not an overwrite.
- **Language belongs to the agent, not the call.** A multilingual role needs one agent version per
  language rather than one agent that switches languages mid-call. The tradeoff is more agents to
  rehearse and publish per job — worth it because Hunar's own API models language at the agent
  level, and a call switching languages mid-stream isn't something the platform supports anyway.
- **The board polls for correctness; webhooks are for speed.** `GET /jobs/{id}/board` refreshes
  stale outreach rows from Hunar on every read, so the board is correct even if a webhook never
  arrives. Webhooks, when they do arrive, just make the board update faster than the next poll
  would. The tradeoff is redundant reads against Hunar — accepted, because a board that's
  sometimes wrong is worse than a board that's sometimes slow to update via one path when the
  other already caught it.
- **Ground-truth qualification is computed in Python, never asked of the model.** A persona's
  `ground_truth.qualified` comes from applying the JD's own `knockout_criteria` to its answers
  (`app/services/personas.py::evaluate_knockouts`), not from asking the LLM whether the persona it
  just wrote should qualify. The tradeoff is a second computation path — worth it because the
  alternative is a self-graded persona, which would make the whole rehearsal loop circular.
- **What rehearsal does NOT prove.** Rehearsal proves the prompt behaves correctly against six
  specific, synthetic personas and a text-only simulated conversation. It does not prove voice
  latency, connection quality, real background noise, a real accent the personas didn't cover, or
  that Hunar's live model matches the simulator's behavior closely enough. That gap is exactly why
  this build still dials a small number of real, consented pilot calls (seeded, see below) rather
  than treating a clean rehearsal score as equivalent to a validated agent.
- **WhatsApp is specified with a seam, not built.** See
  [docs/channel-strategy.md](docs/channel-strategy.md) — voice-first accuracy had to come first in
  three days, and `app/services/consent.py`'s `ConsentChannel` protocol is exactly the seam a real
  implementation would fill in later without touching anything that depends on it.

## Security

- Hunar and NVIDIA keys are server-side only (`backend/app/core/settings.py`) and are never sent
  to `/web` — the frontend's only public env var is `NEXT_PUBLIC_API_BASE_URL`.
- `gitleaks` runs on every commit (`.pre-commit-config.yaml`) and CI independently greps for live
  Hunar/NVIDIA key prefixes on every push (`.github/workflows/ci.yml`'s `secret-scan` job) — two
  layers, because a hook a contributor skipped locally still gets caught centrally.
- Every inbound Hunar webhook is signature-verified (`app/integrations/hunar/signature.py`,
  `hmac.compare_digest`, ±300s timestamp window) before anything it says is trusted, and every
  attempt — valid or not — is logged append-only (`WebhookEvent`) so a forged or replayed webhook
  leaves a trace either way.
- The outbound-call consent guard is unbypassable: no override flag, no env bypass. A number is
  only ever dialled if `consent_recorded_at` is set or the number is explicitly on
  `DEMO_ALLOWED_NUMBERS` — every other candidate is returned in `blocked`, with the exact reason,
  never silently skipped.

## Setup

```bash
git clone <repo> && cd understudy
make up      # Postgres, backend (localhost:8000), web (localhost:3000) — no .env required
make seed    # real, no-key demo data: a rehearsed job, 3 real pilot calls, 40 candidates
```

`GET /healthz` reports which optional integrations (Hunar, NVIDIA, PDL, Gemini) are configured —
the app boots and runs the seeded demo without any of them. To turn them on, or to run either app
outside Docker, copy `backend/.env.example` to `backend/.env` and `web/.env.example` to
`web/.env.local` and fill in what you have.

| Command | What it does |
| --- | --- |
| `make up` | Build and start the full stack (Postgres, backend, web) |
| `make down` | Stop the stack |
| `make seed` | Load the demo seed (idempotent — safe to re-run) |
| `make test` | Backend test suite against a disposable Postgres |
| `make migrate` | Apply Alembic migrations against the running backend container |
| `make gen-api` | Regenerate the web app's TS types from the backend's OpenAPI schema |
| `make fmt` / `make lint` | Format / lint both apps |

Frontend tests: `cd web && npm run test` (vitest) and `npm run test:e2e` (Playwright — needs the
stack up and seeded first; see `web/playwright.config.ts`).

### Env vars

| Var | Example | Boot |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://understudy:understudy@localhost:5432/understudy` | **Required** |
| `CORS_ORIGINS` | `http://localhost:3000` | Optional — defaults to the local web app's origin |
| `HUNAR_API_KEY` | — | Optional — publishing, calling, and webhooks degrade without it |
| `NVIDIA_API_KEY` / `GEMINI_API_KEY` | — | Optional — at least one needed for real compile/rehearse; the seed needs neither |
| `PDL_API_KEY` | — | Optional — sourcing falls back to `backend/fixtures/candidates.json` without it |
| `DEMO_ALLOWED_NUMBERS` | `+15550100000` | Optional — E.164 numbers callable without recorded consent |
| `PUBLIC_BASE_URL` | `https://understudy-backend.onrender.com` | Optional — enables Hunar webhook callbacks; polling keeps the board correct without it |
| `SOURCING_PROVIDER` | `fixtures` \| `pdl` | Optional — default `fixtures` |
| `NEXT_PUBLIC_API_BASE_URL` (web) | `http://localhost:8000` | **Required** — the only public env var |

Deployment: `render.yaml` deploys the backend to Render (Docker, `/healthz` health check); the
frontend deploys to Vercel from source — Vercel does not run `web/Dockerfile`, which exists only
for the `docker compose` setup above and for self-hosting.

## Limitations — what's simulated, what's real

Everything simulated carries an unmissable purple **Simulated** badge in the UI, with a diagonal
hatch so it survives a colourblind or greyscale view — it is never presented as a real result.
`make seed` loads:

- **Real:** three actually-completed pilot calls (English, Tamil, Hindi), each with a real
  recording URL and real Hunar result payload as captured, `is_simulated=False`. Phone numbers in
  the committed fixture are the documented placeholder range
  (`backend/fixtures/README.md`) — never the number actually dialled.
- **Simulated:** all six rehearsal personas' transcripts and scores across all three seeded agent
  versions, and twenty of the forty seeded candidates' outreach rows.

The Hunar key used to record the three real pilot calls expires around this assignment's
deadline — `make seed` is what keeps the rehearsal loop, the board, and the answers view fully
demonstrable after that, from nothing but the committed fixture.

Beyond the simulated/real split: rehearsal validates prompt behaviour against six text-only
personas, not live voice quality (see "What rehearsal does NOT prove" above); WhatsApp messaging
is a documented seam, not a working channel; and the "attendance without apps" answer
([docs/attendance-without-apps.md](docs/attendance-without-apps.md)) is a design document, not
shipped code — both honestly scoped out of a three-day build, not overlooked.
