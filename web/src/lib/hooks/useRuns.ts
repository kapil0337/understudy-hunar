"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
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

export function useProposePatch() {
  return useMutation({
    mutationFn: (runId: string) => api.runs.proposePatch(runId),
  });
}

/** Accepting a patch rehearses the resulting version immediately (CLAUDE.md: a patch's effect is
 * measured, never assumed) — invalidate the job's version list and seed the new run's cache. */
export function useAcceptPatch(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patchId: string) => api.patches.accept(patchId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.versions(jobId) });
      queryClient.setQueryData(queryKeys.runs.detail(data.run.id), data.run);
      queryClient.setQueryData(queryKeys.runs.latestForVersion(data.version.id), data.run);
    },
  });
}
