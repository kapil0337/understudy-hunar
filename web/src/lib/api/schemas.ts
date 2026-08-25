/**
 * Hand-written Zod validators for every JSON response shape the backend returns.
 *
 * `types.ts` is generated (`npm run gen-api`) and gives us compile-time types; it has no runtime
 * component. These schemas are what actually get run against each response body in client.ts, so
 * a live contract break (a renamed field, a dropped nullable) fails loudly as an ApiSchemaError
 * instead of silently as `undefined` three components deep.
 *
 * The `Expect<Equal<...>>` line under each schema is a second, compile-time trip-wire: if a
 * schema drifts from the generated type — including after a `gen-api` re-run — `tsc` fails on
 * that line instead of the mismatch surfacing later as a runtime parse failure.
 */
import { z } from "zod";
import type { components } from "./types";

type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Expect<T extends true> = T;

// ---------------------------------------------------------------------------------------- enums

export const languageSchema = z.enum([
  "ENGLISH",
  "HINDI",
  "TAMIL",
  "TELUGU",
  "KANNADA",
  "MARATHI",
  "MALAYALAM",
  "GUJARATI",
  "BENGALI",
  "TURKISH",
  "ARABIC",
  "SPANISH",
]);
type _CheckLanguage = Expect<Equal<z.infer<typeof languageSchema>, components["schemas"]["Language"]>>;

export const agentVersionOriginSchema = z.enum(["COMPILED", "PATCHED"]);
type _CheckAgentVersionOrigin = Expect<
  Equal<z.infer<typeof agentVersionOriginSchema>, components["schemas"]["AgentVersionOrigin"]>
>;

export const voicePersonaSchema = z.enum(["NEHA", "ROY", "ZOE", "SAM", "MIRA", "EESHA"]);
type _CheckVoicePersona = Expect<
  Equal<z.infer<typeof voicePersonaSchema>, components["schemas"]["VoicePersona"]>
>;

/** Hunar call lifecycle status — see CLAUDE.md. Terminal states: {@link TERMINAL_CALL_STATUSES}. */
export const callStatusSchema = z.enum([
  "NOT_STARTED",
  "SCHEDULED",
  "INITIATED",
  "RINGING",
  "IN_PROGRESS",
  "COMPLETED",
  "NOT_CONNECTED",
  "CANCELLED",
  "FAILED",
]);
export type CallStatus = z.infer<typeof callStatusSchema>;

/** Mirrors backend/app/services/outreach.py's TERMINAL set exactly — do not diverge. */
export const TERMINAL_CALL_STATUSES = new Set<CallStatus>([
  "COMPLETED",
  "NOT_CONNECTED",
  "CANCELLED",
  "FAILED",
]);

export const rehearsalRunStatusSchema = z.enum(["PENDING", "RUNNING", "COMPLETED", "FAILED"]);
export type RehearsalRunStatus = z.infer<typeof rehearsalRunStatusSchema>;

export const weekdaySchema = z.enum([
  "MONDAY",
  "TUESDAY",
  "WEDNESDAY",
  "THURSDAY",
  "FRIDAY",
  "SATURDAY",
  "SUNDAY",
]);
// `Weekday` is a Python Literal, not an enum class, so it has no named OpenAPI component — it's
// inlined wherever it's used. Checked against that inline usage site instead of a named schema.
type _CheckWeekday = Expect<
  Equal<z.infer<typeof weekdaySchema>, components["schemas"]["GuardrailsRead"]["allowed_days"][number]>
>;

const retryIntervalHoursSchema = z.union([
  z.literal(0),
  z.literal(3),
  z.literal(6),
  z.literal(9),
  z.literal(12),
  z.literal(24),
]);

// ------------------------------------------------------------------------------------ envelopes

const jsonRecord = z.record(z.string(), z.unknown());

// -------------------------------------------------------------------------------------- healthz

export const guardrailsReadSchema = z.object({
  allowed_days: z.array(weekdaySchema),
  earliest_call_time: z.string(),
  last_call_time: z.string(),
  timezone: z.string(),
  max_retry_count: z.number(),
  retry_interval_hours: retryIntervalHoursSchema,
  inside_window_now: z.boolean(),
});
type _CheckGuardrailsRead = Expect<
  Equal<z.infer<typeof guardrailsReadSchema>, components["schemas"]["GuardrailsRead"]>
>;

export const healthzResponseSchema = z
  .object({
    status: z.string(),
    environment: z.string(),
    capabilities: z.record(z.string(), z.boolean()),
  })
  .loose();

// ----------------------------------------------------------------------------------------- jobs

export const jobReadSchema = z.object({
  id: z.uuid(),
  title: z.string(),
  raw_jd: z.string(),
  compiled: jsonRecord.nullable(),
  created_at: z.string(),
});
type _CheckJobRead = Expect<Equal<z.infer<typeof jobReadSchema>, components["schemas"]["JobRead"]>>;

export const versionSummarySchema = z.object({
  id: z.uuid(),
  job_id: z.uuid(),
  version_no: z.number(),
  language: languageSchema,
  origin: agentVersionOriginSchema,
  hunar_agent_id: z.string().nullable(),
});
type _CheckVersionSummary = Expect<
  Equal<z.infer<typeof versionSummarySchema>, components["schemas"]["VersionSummary"]>
>;

export const versionHistoryRowSchema = z.object({
  id: z.uuid(),
  version_no: z.number(),
  language: languageSchema,
  origin: agentVersionOriginSchema,
  hunar_agent_id: z.string().nullable(),
  latest_composite_score: z.number().nullable(),
});
type _CheckVersionHistoryRow = Expect<
  Equal<z.infer<typeof versionHistoryRowSchema>, components["schemas"]["VersionHistoryRow"]>
>;

export const agentVersionReadSchema = z.object({
  id: z.uuid(),
  job_id: z.uuid(),
  version_no: z.number(),
  language: languageSchema,
  origin: agentVersionOriginSchema,
  voice_persona: voicePersonaSchema,
  persona_name: z.string(),
  agent_prompt: z.string(),
  objective: z.string(),
  introduction: z.string(),
  result_prompt: z.string(),
  result_schema: jsonRecord,
  hunar_agent_id: z.string().nullable(),
  created_at: z.string(),
});
type _CheckAgentVersionRead = Expect<
  Equal<z.infer<typeof agentVersionReadSchema>, components["schemas"]["AgentVersionRead"]>
>;

export const requirementsUpdateResponseSchema = z.object({
  job_id: z.uuid(),
  versions: z.array(versionSummarySchema),
});
type _CheckRequirementsUpdateResponse = Expect<
  Equal<
    z.infer<typeof requirementsUpdateResponseSchema>,
    components["schemas"]["RequirementsUpdateResponse"]
  >
>;

export const personaReadSchema = z.object({
  id: z.uuid(),
  archetype: z.string(),
  profile: jsonRecord,
  ground_truth: jsonRecord,
  behaviour: jsonRecord,
});
type _CheckPersonaRead = Expect<
  Equal<z.infer<typeof personaReadSchema>, components["schemas"]["PersonaRead"]>
>;

// ----------------------------------------------------------------------------------- candidates

export const candidateReadSchema = z.object({
  id: z.uuid(),
  job_id: z.uuid(),
  source_provider: z.string(),
  source_ref: z.string(),
  full_name: z.string(),
  headline: z.string().nullable(),
  current_title: z.string().nullable(),
  current_company: z.string().nullable(),
  location: z.string().nullable(),
  skills: z.array(z.unknown()),
  years_experience: z.number().nullable(),
  linkedin_url: z.string().nullable(),
  phone_e164: z.string().nullable(),
  preferred_language: languageSchema.nullable(),
  match_score: z.number().nullable(),
  match_breakdown: jsonRecord.nullable(),
  consent_recorded_at: z.string().nullable(),
  consent_channel: z.string().nullable(),
  dnc: z.boolean(),
});
type _CheckCandidateRead = Expect<
  Equal<z.infer<typeof candidateReadSchema>, components["schemas"]["CandidateRead"]>
>;

export const sourceResponseSchema = z.object({
  provider: z.string(),
  cached: z.boolean(),
  candidates: z.array(candidateReadSchema),
});
type _CheckSourceResponse = Expect<
  Equal<z.infer<typeof sourceResponseSchema>, components["schemas"]["SourceResponse"]>
>;

export const queuedCallSchema = z.object({
  candidate_id: z.uuid(),
  outreach_id: z.uuid(),
  request_id: z.string(),
  hunar_call_id: z.string(),
});
type _CheckQueuedCall = Expect<
  Equal<z.infer<typeof queuedCallSchema>, components["schemas"]["QueuedCall"]>
>;

export const blockedCandidateSchema = z.object({
  candidate_id: z.uuid(),
  reason: z.string(),
});
type _CheckBlockedCandidate = Expect<
  Equal<z.infer<typeof blockedCandidateSchema>, components["schemas"]["BlockedCandidate"]>
>;

export const callLaunchSummarySchema = z.object({
  queued: z.array(queuedCallSchema),
  blocked: z.array(blockedCandidateSchema),
  versions_used: z.record(z.string(), z.string()),
  estimated_minutes: z.number(),
});
type _CheckCallLaunchSummary = Expect<
  Equal<z.infer<typeof callLaunchSummarySchema>, components["schemas"]["CallLaunchSummary"]>
>;

// ---------------------------------------------------------------------------------------- board

export const boardRowSchema = z.object({
  candidate_id: z.uuid(),
  full_name: z.string(),
  match_score: z.number().nullable(),
  phone_e164: z.string().nullable(),
  consent_recorded_at: z.string().nullable(),
  dnc: z.boolean(),
  outreach_id: z.string().nullable(),
  agent_version_id: z.uuid().nullable(),
  status: callStatusSchema.nullable(),
  lifecycle_status: z.string().nullable(),
  duration_seconds: z.number().nullable(),
  recording_url: z.string().nullable(),
  result: jsonRecord.nullable(),
  call_summary: z.string().nullable(),
  is_simulated: z.boolean(),
});
// `status` is narrowed from the generated `string | null` to the closed CallStatus enum — an
// exact Equal check would fail on that intentional narrowing, so this one checks structure
// (all other fields) via a partial comparison instead of the full schema.
type _CheckBoardRowShape = Expect<
  Equal<
    Omit<z.infer<typeof boardRowSchema>, "status">,
    Omit<components["schemas"]["BoardRow"], "status">
  >
>;
/** The narrowed type (status: CallStatus, not string) — use this, not
 * `components["schemas"]["BoardRow"]`, wherever a BoardRow is handled after parsing. */
export type BoardRow = z.infer<typeof boardRowSchema>;

export const boardResponseSchema = z.object({
  job_id: z.uuid(),
  rows: z.array(boardRowSchema),
});

// -------------------------------------------------------------------------------------- runs

export const rehearseAcceptedSchema = z.object({
  run_id: z.uuid(),
  status: rehearsalRunStatusSchema,
});

export const caseSummarySchema = z.object({
  id: z.uuid(),
  persona_id: z.uuid(),
  archetype: z.string(),
  turn_count: z.number().nullable(),
  estimated_seconds: z.number().nullable(),
});
type _CheckCaseSummary = Expect<
  Equal<z.infer<typeof caseSummarySchema>, components["schemas"]["CaseSummary"]>
>;

export const runReadSchema = z.object({
  id: z.uuid(),
  agent_version_id: z.uuid(),
  status: rehearsalRunStatusSchema,
  scores: z.record(z.string(), z.unknown()).nullable(),
  llm_calls: z.number(),
  cached_calls: z.number(),
  started_at: z.string(),
  finished_at: z.string().nullable(),
  error: z.string().nullable(),
  case_summaries: z.array(caseSummarySchema),
});

export const caseReadSchema = z.object({
  id: z.uuid(),
  run_id: z.uuid(),
  persona_id: z.uuid(),
  archetype: z.string(),
  transcript: z.array(z.unknown()).nullable(),
  extracted_result: jsonRecord.nullable(),
  ground_truth: jsonRecord,
  metrics: jsonRecord.nullable(),
  failures: z.array(z.unknown()).nullable(),
});
type _CheckCaseRead = Expect<
  Equal<z.infer<typeof caseReadSchema>, components["schemas"]["CaseRead"]>
>;

export const patchReadSchema = z.object({
  id: z.uuid(),
  run_id: z.uuid(),
  proposed_agent_prompt: z.string(),
  rationale: z.array(z.unknown()),
  accepted: z.boolean(),
  resulting_version_id: z.string().nullable(),
});
type _CheckPatchRead = Expect<
  Equal<z.infer<typeof patchReadSchema>, components["schemas"]["PatchRead"]>
>;

export const patchAcceptResponseSchema = z.object({
  version: versionSummarySchema,
  run: runReadSchema,
  score_delta: z.record(z.string(), z.number()),
});

// ------------------------------------------------------------------------------------- webhooks

export const webhookEventReadSchema = z.object({
  id: z.uuid(),
  event_type: z.string(),
  call_id: z.string().nullable(),
  request_id: z.string().nullable(),
  signature_valid: z.boolean(),
  raw_payload: jsonRecord,
  received_at: z.string(),
});
type _CheckWebhookEventRead = Expect<
  Equal<z.infer<typeof webhookEventReadSchema>, components["schemas"]["WebhookEventRead"]>
>;

// --------------------------------------------------------------------------------------- errors

export const validationErrorSchema = z.object({
  loc: z.array(z.union([z.string(), z.number()])),
  msg: z.string(),
  type: z.string(),
  input: z.unknown().optional(),
  ctx: z.record(z.string(), z.never()).optional(),
});

export const httpValidationErrorSchema = z.object({
  detail: z.array(validationErrorSchema).optional(),
});
