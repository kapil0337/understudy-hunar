/**
 * The one typed fetch wrapper. Every route the app calls goes through `request()` below, which
 * builds the URL, sends the request, and Zod-parses the response — a schema mismatch throws
 * ApiSchemaError naming the path, so a backend contract change surfaces here instead of as
 * `undefined` deep in a component. NEXT_PUBLIC_API_BASE_URL is the only public env var (CLAUDE.md
 * — Hunar/NVIDIA keys are server-side-only and must never reach this file's counterpart on the
 * server side of the fence).
 */
import { z } from "zod";
import type { components } from "./types";
import {
  agentVersionReadSchema,
  backgroundJobReadSchema,
  boardResponseSchema,
  callLaunchSummarySchema,
  candidateReadSchema,
  caseReadSchema,
  guardrailsReadSchema,
  healthzResponseSchema,
  httpValidationErrorSchema,
  jobReadSchema,
  patchAcceptAcceptedSchema,
  patchProposalAcceptedSchema,
  patchReadSchema,
  personasResponseSchema,
  rehearseAcceptedSchema,
  requirementsUpdateAcceptedSchema,
  runReadSchema,
  sourceResponseSchema,
  versionHistoryRowSchema,
  versionSummarySchema,
  webhookEventReadSchema,
} from "./schemas";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

/** Thrown for any non-2xx response. `message` is always the backend's own message, never a
 * generic fallback — the Shell surfaces this directly in a toast (see design notes). */
export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

/** Thrown when a response is valid JSON but doesn't match the schema we expected for that path —
 * i.e. the backend's contract moved out from under us. */
export class ApiSchemaError extends Error {
  readonly path: string;
  readonly issues: z.ZodIssue[];

  constructor(path: string, issues: z.ZodIssue[]) {
    const detail = issues
      .map((issue) => `${issue.path.join(".") || "<root>"}: ${issue.message}`)
      .join("; ");
    super(`Response for ${path} did not match the expected schema — ${detail}`);
    this.name = "ApiSchemaError";
    this.path = path;
    this.issues = issues;
  }
}

async function messageFromErrorBody(
  status: number,
  body: unknown,
): Promise<string> {
  const parsed = httpValidationErrorSchema.safeParse(body);
  if (parsed.success && parsed.data.detail) {
    return parsed.data.detail
      .map((e) => `${e.loc.join(".")}: ${e.msg}`)
      .join("; ");
  }
  if (
    body &&
    typeof body === "object" &&
    "detail" in body &&
    typeof body.detail === "string"
  ) {
    return body.detail;
  }
  return `Request failed with status ${status}`;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions<T> {
  method?: Method;
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  schema: z.ZodType<T>;
  signal?: AbortSignal;
}

function buildUrl(
  path: string,
  query?: RequestOptions<unknown>["query"],
): string {
  if (!API_BASE_URL) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL is not set — copy web/.env.example to .env.local and fill it in.",
    );
  }
  const base = API_BASE_URL.replace(/\/$/, "");
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) search.set(key, String(value));
  }
  const qs = search.toString();
  return `${base}${path}${qs ? `?${qs}` : ""}`;
}

async function request<T>(
  path: string,
  options: RequestOptions<T>,
): Promise<T> {
  const { method = "GET", query, body, schema, signal } = options;
  const url = buildUrl(path, query);

  const response = await fetch(url, {
    method,
    headers:
      body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  // A 204 (or any empty body) can still carry a `content-type: application/json` header —
  // FastAPI does this for routes with no response model — so `.json()` isn't safe to call on
  // content-type alone; it throws on an empty string instead of just returning undefined.
  const contentType = response.headers.get("content-type") ?? "";
  const text = contentType.includes("application/json")
    ? await response.text()
    : "";
  const raw = text.length > 0 ? JSON.parse(text) : undefined;

  if (!response.ok) {
    throw new ApiError(
      response.status,
      await messageFromErrorBody(response.status, raw),
      raw,
    );
  }

  const result = schema.safeParse(raw);
  if (!result.success) {
    throw new ApiSchemaError(path, result.error.issues);
  }
  return result.data;
}

// -------------------------------------------------------------------------------- request bodies
// Request bodies are sent, not parsed — they're typed straight from the generated schema rather
// than re-validated with Zod, since `request()`'s job is to validate what comes back, not what we
// send (CLAUDE.md: "Every response Zod-parsed").

type JobCreate = components["schemas"]["JobCreate"];
type RequirementsUpdate = components["schemas"]["RequirementsUpdate"];
type SourceRequest = components["schemas"]["SourceRequest"];
type CallRequest = components["schemas"]["CallRequest"];
type CandidatePatch = components["schemas"]["CandidatePatch"];
type ConsentCreate = components["schemas"]["ConsentCreate"];
type Language = components["schemas"]["Language"];

// ------------------------------------------------------------------------------------------ api

export const api = {
  healthz: (signal?: AbortSignal) =>
    request("/healthz", { schema: healthzResponseSchema, signal }),

  guardrails: {
    get: (signal?: AbortSignal) =>
      request("/guardrails", { schema: guardrailsReadSchema, signal }),
  },

  jobs: {
    list: (signal?: AbortSignal) =>
      request("/jobs", { schema: z.array(jobReadSchema), signal }),

    get: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}`, { schema: jobReadSchema, signal }),

    create: (body: JobCreate, signal?: AbortSignal) =>
      request("/jobs", { method: "POST", body, schema: jobReadSchema, signal }),

    /** Deletes the job and everything scoped to it — candidates, outreach/call history, agent
     * versions, rehearsal runs/cases, patches. Irreversible; 204 on success. */
    delete: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}`, { method: "DELETE", schema: z.void(), signal }),

    /** Compiling is an LLM call — returns 202 + a background_job_id immediately; poll
     * api.backgroundJobs.get, then refetch versions once COMPLETED. */
    updateRequirements: (
      jobId: string,
      body: RequirementsUpdate,
      signal?: AbortSignal,
    ) =>
      request(`/jobs/${jobId}/requirements`, {
        method: "PUT",
        body,
        schema: requirementsUpdateAcceptedSchema,
        signal,
      }),

    listVersions: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/versions`, {
        schema: z.array(versionHistoryRowSchema),
        signal,
      }),

    publishVersion: (
      jobId: string,
      versionNo: number,
      language: Language,
      signal?: AbortSignal,
    ) =>
      request(`/jobs/${jobId}/versions/${versionNo}/publish`, {
        method: "POST",
        query: { language },
        schema: versionSummarySchema,
        signal,
      }),

    /** Returns the generated personas, or a background_job_id to poll on the first call for a
     * job (generating them is an LLM call) — see personasResponseSchema. */
    listPersonas: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/personas`, {
        schema: personasResponseSchema,
        signal,
      }),

    sourceCandidates: (
      jobId: string,
      body: SourceRequest,
      signal?: AbortSignal,
    ) =>
      request(`/jobs/${jobId}/source`, {
        method: "POST",
        body,
        schema: sourceResponseSchema,
        signal,
      }),

    listCandidates: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/candidates`, {
        schema: z.array(candidateReadSchema),
        signal,
      }),

    launchCalls: (jobId: string, body: CallRequest, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/call`, {
        method: "POST",
        body,
        schema: callLaunchSummarySchema,
        signal,
      }),

    board: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/board`, { schema: boardResponseSchema, signal }),

    /** Not fetched — the CSV is meant to be downloaded directly, e.g. via `<a href={...}>`. */
    exportUrl: (jobId: string) => buildUrl(`/jobs/${jobId}/export`),
  },

  versions: {
    get: (versionId: string, signal?: AbortSignal) =>
      request(`/versions/${versionId}`, {
        schema: agentVersionReadSchema,
        signal,
      }),

    rehearse: (versionId: string, signal?: AbortSignal) =>
      request(`/versions/${versionId}/rehearse`, {
        method: "POST",
        schema: rehearseAcceptedSchema,
        signal,
      }),

    /** null when the version has never been rehearsed — a valid state, not an error. */
    latestRun: (versionId: string, signal?: AbortSignal) =>
      request(`/versions/${versionId}/latest-run`, {
        schema: runReadSchema.nullable(),
        signal,
      }),
  },

  runs: {
    get: (runId: string, signal?: AbortSignal) =>
      request(`/runs/${runId}`, { schema: runReadSchema, signal }),

    getCase: (runId: string, caseId: string, signal?: AbortSignal) =>
      request(`/runs/${runId}/cases/${caseId}`, {
        schema: caseReadSchema,
        signal,
      }),

    /** Proposing a patch is an LLM call — returns 202 + a background_job_id; poll
     * api.backgroundJobs.get, then api.patches.get(result.patch_id) once COMPLETED. */
    proposePatch: (runId: string, signal?: AbortSignal) =>
      request(`/runs/${runId}/patch`, {
        method: "POST",
        schema: patchProposalAcceptedSchema,
        signal,
      }),
  },

  patches: {
    get: (patchId: string, signal?: AbortSignal) =>
      request(`/patches/${patchId}`, { schema: patchReadSchema, signal }),

    /** The new version exists immediately; rehearsing it is deferred — poll
     * api.versions.latestRun(result.version.id) for the run. */
    accept: (patchId: string, signal?: AbortSignal) =>
      request(`/patches/${patchId}/accept`, {
        method: "POST",
        schema: patchAcceptAcceptedSchema,
        signal,
      }),
  },

  backgroundJobs: {
    get: (backgroundJobId: string, signal?: AbortSignal) =>
      request(`/background-jobs/${backgroundJobId}`, {
        schema: backgroundJobReadSchema,
        signal,
      }),
  },

  candidates: {
    patch: (candidateId: string, body: CandidatePatch, signal?: AbortSignal) =>
      request(`/candidates/${candidateId}`, {
        method: "PATCH",
        body,
        schema: candidateReadSchema,
        signal,
      }),

    recordConsent: (
      candidateId: string,
      body: ConsentCreate,
      signal?: AbortSignal,
    ) =>
      request(`/candidates/${candidateId}/consent`, {
        method: "POST",
        body,
        schema: candidateReadSchema,
        signal,
      }),
  },

  debug: {
    listWebhookEvents: (limit?: number, signal?: AbortSignal) =>
      request("/debug/webhooks", {
        query: { limit },
        schema: z.array(webhookEventReadSchema),
        signal,
      }),
  },
};
