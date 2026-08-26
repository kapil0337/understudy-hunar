# Understudy

Rehearse-then-dial voice recruiting on the Hunar Voice Agents API.
Assignment submission. Deadline Aug 27 2026.

## Hard rules
- Never write a real API key, phone number, or PII into source, tests, fixtures, commit messages,
  or logs. Add a log redaction filter for the key patterns.
- Hunar and NVIDIA keys are server-side only. They must never reach /web.
- Outbound calls are blocked unless the number is in DEMO_ALLOWED_NUMBERS or the candidate row has
  consent_recorded_at set. No override flag, no env bypass.
- Every external HTTP call goes through an adapter in app/integrations/ with a typed response
  model, a timeout, and a retry policy. No raw httpx in route handlers.
- Route handlers thin. Logic in app/services/.
- Python: full type hints, Pydantic v2 at boundaries, mypy strict passes.
- TypeScript: strict, no `any`, Zod-parse every API response.
- Every LLM call goes through app/services/llm.py with role compiler | simulator, and is cached by
  sha256(role, model, messages, schema). Caching is not an optimisation here, it is what makes
  iterating on the rehearsal loop affordable.

## Hunar API facts (do not guess these)
- Base https://api.voice.hunar.ai/external/v1/ , auth header X-API-Key
- Agents: GET /agents/, GET /agents/{id}/, POST /agents/, PUT /agents/{id}/
- Calls: POST /calls/, GET /calls/, GET /calls/{id}/
- Numbers: GET /numbers/
- Agent create requires name, language, voice_persona, agent_prompt, objective, introduction,
  result_prompt, result_schema
- voice_persona in NEHA, ROY, ZOE, SAM, MIRA, EESHA
- language in ENGLISH, HINDI, TAMIL, TELUGU, KANNADA, MARATHI, MALAYALAM, GUJARATI, BENGALI,
  TURKISH, ARABIC, SPANISH. Language belongs to the AGENT, not the call.
- Updating voice_persona or language requires resending name, objective, language, voice_persona,
  persona_name, agent_prompt, introduction, result_prompt, result_schema together.
- Call create needs agent_id, callee_name, mobile_number in E.164, and custom_data containing
  EVERY key in the agent's custom_variables, else 422.
- retry_config must be complete: max_retry_count 0-10, retry_interval_hours in 0,3,6,9,12,24.
  Request field max_retry_count, response field max_retries.
- guardrails must be complete: allowed_days min 3 distinct, earliest_call_time HH:MM,
  last_call_time HH:MM, window at least 3 hours. Omit to inherit org defaults.
- callback_config: call_status_callback_url, call_recording_callback_url,
  call_result_callback_url, call_summary_callback_url
- Webhook signature headers: X-Hunar-Signature carries the signature, X-Hunar-Timestamp the
  timestamp. Signature is base64 HMAC-SHA256 over f"{X-Hunar-Timestamp}.".encode() + raw body
  bytes, keyed by the API key. Comma-separated segments possible. hmac.compare_digest. Reject
  timestamps outside 300s.
- Statuses: NOT_STARTED, SCHEDULED, INITIATED, RINGING, IN_PROGRESS, COMPLETED, NOT_CONNECTED,
  CANCELLED, FAILED. Creates return 200. Errors are {success, message, details}.
- There is NO transcript field. You get recording_url and a `result` object shaped by result_schema.

## Style
Boring readable code over clever code. Small commits. When unsure about API behaviour, write the
adapter defensively, log the raw response, never invent fields.