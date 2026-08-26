"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useBackgroundJob } from "./useBackgroundJobs";
import { queryKeys } from "./queryKeys";

/** Polls at 2s while the run is PENDING or RUNNING (both non-terminal — PENDING is the brief
 * window between the 202 and the background task's first write) and stops once it lands on
 * COMPLETED or FAILED. */
export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.runs.detail(runId ?? ""),
    queryFn: ({ signal }) => api.runs.get(runId as string, signal),
    enabled: runId !== undefined,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "PENDING" || status === "RUNNING" ? 2000 : false;
    },
  });
}

/** Used by the board drawer to trace a call back to the rehearsal run for the version that
 * placed it (BoardRow.agent_version_id), so it can show what the closest rehearsed archetype
 * predicted beside the real result. null both while loading is disabled and once loaded if the
 * version has never been rehearsed. */
export function useLatestRun(versionId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.runs.latestForVersion(versionId ?? ""),
    queryFn: ({ signal }) => api.versions.latestRun(versionId as string, signal),
    enabled: versionId !== undefined,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "PENDING" || status === "RUNNING" ? 2000 : false;
    },
  });
}

export function useCase(runId: string | undefined, caseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.runs.case(runId ?? "", caseId ?? ""),
    queryFn: ({ signal }) => api.runs.getCase(runId as string, caseId as string, signal),
    enabled: runId !== undefined && caseId !== undefined,
  });
}

/** Proposing a patch is an LLM call, deferred to app/worker.py — the mutation itself only gets
 * back a background_job_id. This polls that (useBackgroundJob) and, once COMPLETED, fetches the
 * actual patch (result.patch_id) — so callers see one `data: PatchRead | undefined`, same shape
 * as before this was made async. */
export function useProposePatch() {
  const [backgroundJobId, setBackgroundJobId] = useState<string | undefined>(undefined);

  const mutation = useMutation({
    mutationFn: (runId: string) => api.runs.proposePatch(runId),
    onSuccess: (data) => setBackgroundJobId(data.background_job_id),
  });
  const backgroundJob = useBackgroundJob(backgroundJobId);
  const patchId =
    backgroundJob.data?.status === "COMPLETED" &&
    typeof backgroundJob.data.result?.patch_id === "string"
      ? backgroundJob.data.result.patch_id
      : undefined;

  const patchQuery = useQuery({
    queryKey: queryKeys.patches.detail(patchId ?? ""),
    queryFn: ({ signal }) => api.patches.get(patchId as string, signal),
    enabled: patchId !== undefined,
  });

  return {
    mutate: mutation.mutate,
    reset: () => {
      mutation.reset();
      setBackgroundJobId(undefined);
    },
    data: patchQuery.data,
    isPending:
      mutation.isPending ||
      backgroundJob.data?.status === "PENDING" ||
      backgroundJob.data?.status === "RUNNING" ||
      (patchId !== undefined && patchQuery.isPending),
    isError: mutation.isError || backgroundJob.data?.status === "FAILED" || patchQuery.isError,
    error:
      backgroundJob.data?.status === "FAILED"
        ? new Error(backgroundJob.data.error ?? "Patch proposal failed")
        : (mutation.error ?? patchQuery.error),
  };
}

/** Accepting a patch creates the new version immediately, but rehearsing it is deferred to
 * app/worker.py — poll useLatestRun(version.id) for the run itself (CLAUDE.md: a patch's effect
 * is measured, never assumed, so the caller still needs that run to complete). */
export function useAcceptPatch(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patchId: string) => api.patches.accept(patchId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.versions(jobId) });
    },
  });
}
