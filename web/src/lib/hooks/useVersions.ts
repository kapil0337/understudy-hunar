"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/types";
import { queryKeys } from "./queryKeys";

type Language = components["schemas"]["Language"];

export function useJobVersions(jobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.jobs.versions(jobId ?? ""),
    queryFn: ({ signal }) => api.jobs.listVersions(jobId as string, signal),
    enabled: jobId !== undefined,
  });
}

/** Full built agent_prompt/result_schema for one version — not part of VersionSummary/
 * VersionHistoryRow, only fetched where the actual text is needed (e.g. diffing a proposed
 * patch against the version it would replace). */
export function useVersion(versionId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.jobs.versionDetail(versionId ?? ""),
    queryFn: ({ signal }) => api.versions.get(versionId as string, signal),
    enabled: versionId !== undefined,
  });
}

/** Updating voice_persona or language requires resending the full agent shape together — the
 * caller assembles that body; this hook only owns the request/invalidate cycle (CONTRIBUTING.md). */
export function usePublishVersion(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ versionNo, language }: { versionNo: number; language: Language }) =>
      api.jobs.publishVersion(jobId, versionNo, language),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.versions(jobId) });
    },
  });
}

export function useRehearseVersion(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) => api.versions.rehearse(versionId),
    onSuccess: (_data, versionId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.versions(jobId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.runs.latestForVersion(versionId) });
    },
  });
}
