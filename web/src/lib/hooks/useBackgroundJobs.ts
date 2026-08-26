"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "./queryKeys";

/** Polls at 2s while PENDING/RUNNING, stops once COMPLETED/FAILED — the one generic status
 * endpoint every LLM-heavy operation deferred to app/worker.py shares (compile_jd,
 * regenerate_personas, propose_patch, rehearse). Same pattern as useRuns.ts's useRun/
 * useLatestRun, which poll the equivalent status field on RehearsalRun directly. */
export function useBackgroundJob(backgroundJobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.backgroundJobs.detail(backgroundJobId ?? ""),
    queryFn: ({ signal }) => api.backgroundJobs.get(backgroundJobId as string, signal),
    enabled: backgroundJobId !== undefined,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "PENDING" || status === "RUNNING" ? 2000 : false;
    },
  });
}
