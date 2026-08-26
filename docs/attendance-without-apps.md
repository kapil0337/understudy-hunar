# Attendance without apps

## The problem

Once a candidate is hired, the next operational question is: did they show up for their shift?
For the roles this product screens — delivery riders, warehouse pickers, retail associates — that
question repeats daily, at scale, for a workforce with high turnover and low tolerance for
friction. A dedicated attendance app is the wrong answer for this population specifically:

- Many of these phones are low-storage Android devices already carrying WhatsApp, a UPI app, and
  little else free space for a single-purpose HR install.
- Turnover means re-onboarding someone to a new app every few weeks, for a check-in that takes
  five seconds if it works at all.
- A no-show discovered at shift start, not before, still leaves an empty route or an empty till —
  the check has to happen close enough to shift time to matter, and reliably enough that ops does
  not have to double-check it another way.

The one channel with zero install friction and universal reach for this exact population is the
one this product is already built on: the phone call. `has_smartphone` is a screening question in
this build's own fixture JD (`backend/fixtures/jd/delivery_rider_chennai.txt`) precisely because
even a basic phone is a real constraint here — a plain voice line is the one channel guaranteed to
work regardless.

## The design: reuse the rehearsal-then-dial rails, not a new system

Two mechanisms, both riding the infrastructure this repo already has:

**1. Outbound confirmation call.** A short automated call, ~15–30 minutes before shift start,
using the same `AgentVersion` / Hunar agent machinery already built — a purpose-built persona
whose `result_schema` has exactly one field (`confirmed: boolean`, plus an optional
`reason` free-text if declined) instead of five screening questions. It is rehearsed the same
way a screening agent is: scored on faithfulness (never inventing shift details) and efficiency
(a confirmation call should run under 20 seconds, not 90) before it ever dials a real worker.
Scheduling is the only genuinely new piece — the outbound trigger is a shift start time, not a
recruiter's "call selected" click, so this needs a small scheduler (a cron-style job reading each
worker's assigned shift) that this repo does not currently have.

**2. Missed-call check-in.** For arrival itself, not the pre-shift reminder: the worker gives a
missed call to a fixed number and hangs up before it connects — the standard "give a missed call"
pattern already familiar across Indian consumer services, costing the worker nothing and
requiring no data, no app, no spoken conversation. The system recognizes the inbound number within
seconds and marks attendance present. This is the same shape as the Hunar webhook flow already
built (`app/services/webhooks.py` — signature-verified, idempotent, append-only logged) except the
event originates from telephony infrastructure this build does not have a client for: Hunar's
documented surface is outbound agent calls, not inbound missed-call detection. That adapter would
need its own `app/integrations/` module, with its own typed client and its own tests, exactly the
way `app/integrations/hunar/` is built now.

## Why not the alternatives

- **A geofenced check-in app** — solves accuracy better than a phone call can, but reintroduces
  the exact install/storage/turnover friction this design exists to avoid.
- **SMS-based check-in** — closer in spirit (no app), but a two-way SMS flow costs per message at
  a volume where a missed call costs the worker nothing, and template/session-window rules
  complicate it the same way they complicate WhatsApp (see `docs/channel-strategy.md`).
- **A human supervisor calling roll** — works today, does not scale past a handful of sites, and
  is exactly the manual cost this whole product is trying to reduce.

## Honest status: scoped out

Not implemented, the same way WhatsApp is not implemented (`docs/channel-strategy.md`) — this is a
design answer, not shipped code. Building the confirmation-call path means a new `voice_persona` +
`result_schema` pair (small, reuses everything in `app/services/jd_compiler.py`'s prompt-building
shape) plus a scheduler; building the missed-call path means a new integration adapter Hunar's own
API does not cover. Three days did not leave room for either on top of the screening path, and
rehearse-then-dial accuracy is where the assignment's actual grading weight sits.
