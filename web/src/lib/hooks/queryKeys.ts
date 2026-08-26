/**
 * Single source of truth for TanStack Query cache keys. Nothing outside this file should write an
 * inline key array — that's how a typo silently creates a second, never-invalidated cache entry.
 */
export const queryKeys = {
  healthz: () => ["healthz"] as const,
  guardrails: () => ["guardrails"] as const,

  jobs: {
    all: () => ["jobs"] as const,
    lists: () => [...queryKeys.jobs.all(), "list"] as const,
    detail: (jobId: string) => [...queryKeys.jobs.all(), "detail", jobId] as const,
    versions: (jobId: string) => [...queryKeys.jobs.all(), jobId, "versions"] as const,
    versionDetail: (versionId: string) => [...queryKeys.jobs.all(), "version", versionId] as const,
    personas: (jobId: string) => [...queryKeys.jobs.all(), jobId, "personas"] as const,
    candidates: (jobId: string) => [...queryKeys.jobs.all(), jobId, "candidates"] as const,
    board: (jobId: string) => [...queryKeys.jobs.all(), jobId, "board"] as const,
  },

  runs: {
    all: () => ["runs"] as const,
    detail: (runId: string) => [...queryKeys.runs.all(), "detail", runId] as const,
    case: (runId: string, caseId: string) =>
      [...queryKeys.runs.all(), "detail", runId, "cases", caseId] as const,
    latestForVersion: (versionId: string) =>
      [...queryKeys.runs.all(), "latest-for-version", versionId] as const,
  },

  patches: {
    detail: (patchId: string) => ["patches", "detail", patchId] as const,
  },

  backgroundJobs: {
    detail: (backgroundJobId: string) => ["backgroundJobs", "detail", backgroundJobId] as const,
  },

  debug: {
    webhookEvents: (limit?: number) => ["debug", "webhookEvents", limit] as const,
  },
} as const;
