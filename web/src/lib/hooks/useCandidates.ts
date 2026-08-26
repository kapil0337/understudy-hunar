"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/types";
import { queryKeys } from "./queryKeys";

type SourceRequest = components["schemas"]["SourceRequest"];
type CallRequest = components["schemas"]["CallRequest"];
type CandidatePatch = components["schemas"]["CandidatePatch"];
type ConsentCreate = components["schemas"]["ConsentCreate"];

export function useJobCandidates(jobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.jobs.candidates(jobId ?? ""),
    queryFn: ({ signal }) => api.jobs.listCandidates(jobId as string, signal),
    enabled: jobId !== undefined,
  });
}

export function useSourceCandidates(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SourceRequest) => api.jobs.sourceCandidates(jobId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.candidates(jobId) });
    },
  });
}

/** The consent/DNC guard is unbypassable server-side (CONTRIBUTING.md) — this hook just surfaces
 * whatever `blocked` list comes back in CallLaunchSummary; it never filters candidates itself. */
export function useLaunchCalls(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CallRequest) => api.jobs.launchCalls(jobId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.board(jobId) });
    },
  });
}

export function usePatchCandidate(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ candidateId, body }: { candidateId: string; body: CandidatePatch }) =>
      api.candidates.patch(candidateId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.candidates(jobId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.board(jobId) });
    },
  });
}

export function useRecordConsent(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ candidateId, body }: { candidateId: string; body: ConsentCreate }) =>
      api.candidates.recordConsent(candidateId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.candidates(jobId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.board(jobId) });
    },
  });
}
