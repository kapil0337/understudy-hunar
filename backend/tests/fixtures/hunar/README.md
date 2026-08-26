# Hunar API fixtures

These JSON files are what `respx` replays in the test suite, so the suite keeps running after
the Hunar API key expires.

## Status: REAL — captured 2026-08-26

The read-path fixtures (`agents_list.json`, `agent_detail.json`, `calls_list.json`,
`call_detail.json`, `numbers_list.json`) are real, scrubbed captures from the live API, taken
2026-08-26. The org had 0 numbers provisioned at capture time, so `numbers_list.json` has an
empty `results`; `allowed_countries` extraction is covered instead by
`test_hunar_preflight.py`'s `check_destination_allowed` tests against directly-constructed
`PhoneNumber` objects.

The capture surfaced one real adapter bug, now fixed: `guardrails.allowed_days` comes back as
3-letter codes (`MON`, `TUE`, …), not the full weekday names (`MONDAY`, `TUESDAY`, …) the
adapter previously assumed.

It also surfaced a scrubber bug, now fixed: a call's `result` is LLM-generated prose about a
real candidate (name, salary, what they said) shaped by whatever `result_schema` the agent
declares — scrubbing by known key name alone (`callee_name`, etc.) missed it entirely, and an
earlier capture briefly committed real candidate names and CTC figures buried in `result.summary`
/ `result.call_summary` / etc. `capture_hunar_fixtures.py` now scrubs every string value nested
under a call's `result` wholesale (`scripts/capture_hunar_fixtures.py`'s `in_result` handling),
keeping only Hunar's own `"NOT AVAILABLE"` sentinel. See
`tests/integrations/test_capture_scrubber.py::test_replaces_free_text_inside_call_result`.

`call_detail.json` in particular reflects whichever call was most recent on the live account at
capture time — it has been a completed call with a result in one capture and an in-progress call
with an empty result and null recording_url in another. Tests that need a specific completed
call use one picked out of `calls_list.json` by id instead of depending on `call_detail.json`'s
current content.

The write-path fixtures (`agent_created.json`, `agent_updated.json`, `call_created.json`) and
the `error_*` / `webhook_*` files are still hand-written — those endpoints have side effects or
aren't captured automatically. Treat them as SYNTHETIC until captured by hand.

Re-capture the read-path fixtures with:

```bash
export HUNAR_API_KEY=...           # while the key is still valid
uv run python scripts/capture_hunar_fixtures.py
```

That script performs read-only calls (`GET /agents/`, `GET /calls/`, `GET /numbers/`), scrubs
the response, and overwrites the read-path fixtures below. Review the diff before committing —
if a real response differs in shape from what is here, that difference is a finding about the
adapter, not a problem with the fixture.

The write paths (`agent_created`, `agent_updated`, `call_created`) and the `error_*` files are
not captured automatically: creating agents and placing calls has side effects and costs
minutes. Capture those by hand if and when you exercise those endpoints for real.

## Scrubbing rules

Nothing in this directory may contain a real secret, phone number, recording URL, or candidate
name. `capture_hunar_fixtures.py` enforces this automatically; keep to it for manual edits too.

| Real value          | Replaced with                                              |
| ------------------- | ---------------------------------------------------------- |
| API keys / tokens   | removed entirely                                           |
| Agent / call / number ids | `agt_0000…`, `cal_0000…`, `num_0000…`                |
| Indian numbers      | `+919876543210`                                            |
| US numbers          | `+12025550123`                                             |
| Recording URLs      | `https://recordings.example.invalid/scrubbed/…`            |
| Person names        | `Test Candidate`                                           |

The placeholder numbers are fictional-but-valid on purpose: `preflight.check_mobile_number`
runs them through `phonenumbers`, so a number that fails validation would make the fixtures
useless for testing the happy path. (`+15550100000`, used elsewhere in `backend/fixtures/`, is
*not* valid per libphonenumber — don't use it here.)

`.example.invalid` is used for URLs because `.invalid` is reserved by RFC 2606 and can never
resolve to a real host.

## Files

| File | Endpoint |
| ---- | -------- |
| `agents_list.json` | `GET /agents/` |
| `agent_detail.json` | `GET /agents/{id}/` |
| `agent_created.json` | `POST /agents/` |
| `agent_updated.json` | `PUT /agents/{id}/` |
| `calls_list.json` | `GET /calls/` |
| `call_detail.json` | `GET /calls/{id}/` |
| `call_created.json` | `POST /calls/` |
| `numbers_list.json` | `GET /numbers/` |
| `error_4xx_*.json` | the `{success, message, details}` envelope per status |
| `webhook_call_*.json` | the four callback payloads |
