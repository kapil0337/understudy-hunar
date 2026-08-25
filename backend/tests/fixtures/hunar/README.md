# Hunar API fixtures

These JSON files are what `respx` replays in the test suite, so the suite keeps running after
the Hunar API key expires.

## Status: SYNTHETIC — replace with real captures while the key is alive

**These fixtures were hand-written from the API contract in [CLAUDE.md](../../../../CLAUDE.md),
not captured from the live API.** No API key was available when they were created. They encode
what the documentation says the responses look like, which is exactly the assumption most worth
verifying against reality.

Until they are replaced with real captures, a passing test suite proves the adapter is
self-consistent — not that it matches what Hunar actually returns.

Replace them with:

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
