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
  boardResponseSchema,
  callLaunchSummarySchema,
  candidateReadSchema,
  caseReadSchema,
  healthzResponseSchema,
  httpValidationErrorSchema,
  jobReadSchema,
  patchAcceptResponseSchema,
  patchReadSchema,
  personaReadSchema,
  rehearseAcceptedSchema,
  requirementsUpdateResponseSchema,
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

async function messageFromErrorBody(status: number, body: unknown): Promise<string> {
  const parsed = httpValidationErrorSchema.safeParse(body);
  if (parsed.success && parsed.data.detail) {
    return parsed.data.detail.map((e) => `${e.loc.join(".")}: ${e.msg}`).join("; ");
  }
  if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
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

function buildUrl(path: string, query?: RequestOptions<unknown>["query"]): string {
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

async function request<T>(path: string, options: RequestOptions<T>): Promise<T> {
  const { method = "GET", query, body, schema, signal } = options;
  const url = buildUrl(path, query);

  const response = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  const contentType = response.headers.get("content-type") ?? "";
  const raw = contentType.includes("application/json") ? await response.json() : undefined;

  if (!response.ok) {
    throw new ApiError(response.status, await messageFromErrorBody(response.status, raw), raw);
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
  healthz: (signal?: AbortSignal) => request("/healthz", { schema: healthzResponseSchema, signal }),

  jobs: {
    list: (signal?: AbortSignal) =>
      request("/jobs", { schema: z.array(jobReadSchema), signal }),

    get: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}`, { schema: jobReadSchema, signal }),

    create: (body: JobCreate, signal?: AbortSignal) =>
      request("/jobs", { method: "POST", body, schema: jobReadSchema, signal }),

    updateRequirements: (jobId: string, body: RequirementsUpdate, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/requirements`, {
        method: "PUT",
        body,
        schema: requirementsUpdateResponseSchema,
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

    listPersonas: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/personas`, { schema: z.array(personaReadSchema), signal }),

    sourceCandidates: (jobId: string, body: SourceRequest, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/source`, {
        method: "POST",
        body,
        schema: sourceResponseSchema,
        signal,
      }),

    listCandidates: (jobId: string, signal?: AbortSignal) =>
      request(`/jobs/${jobId}/candidates`, { schema: z.array(candidateReadSchema), signal }),

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
    rehearse: (versionId: string, signal?: AbortSignal) =>
      request(`/versions/${versionId}/rehearse`, {
        method: "POST",
        schema: rehearseAcceptedSchema,
        signal,
      }),
  },

  runs: {
    get: (runId: string, signal?: AbortSignal) =>
      request(`/runs/${runId}`, { schema: runReadSchema, signal }),

    getCase: (runId: string, caseId: string, signal?: AbortSignal) =>
      request(`/runs/${runId}/cases/${caseId}`, { schema: caseReadSchema, signal }),

    proposePatch: (runId: string, signal?: AbortSignal) =>
      request(`/runs/${runId}/patch`, { method: "POST", schema: patchReadSchema, signal }),
  },

  patches: {
    accept: (patchId: string, signal?: AbortSignal) =>
      request(`/patches/${patchId}/accept`, {
        method: "POST",
        schema: patchAcceptResponseSchema,
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

    recordConsent: (candidateId: string, body: ConsentCreate, signal?: AbortSignal) =>
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
