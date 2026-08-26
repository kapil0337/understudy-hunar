"use client";

import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useBackgroundJob } from "./useBackgroundJobs";
import { queryKeys } from "./queryKeys";

/** GET /jobs/{id}/personas returns the generated list, or (on the first call for a job) a
 * background_job_id to poll — generating personas is an LLM call, deferred to app/worker.py.
 * This hook hides that behind a single `data: PersonaRead[] | undefined`, polling and
 * refetching automatically once generation completes. */
export function useJobPersonas(jobId: string | undefined) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.jobs.personas(jobId ?? ""),
    queryFn: ({ signal }) => api.jobs.listPersonas(jobId as string, signal),
    enabled: jobId !== undefined,
  });

  const backgroundJobId =
    query.data !== undefined && !Array.isArray(query.data)
      ? query.data.background_job_id
      : undefined;
  const isGenerating = backgroundJobId !== undefined;
  const backgroundJob = useBackgroundJob(backgroundJobId);
  const backgroundJobStatus = backgroundJob.data?.status;

  useEffect(() => {
    if (jobId === undefined) return;
    if (backgroundJobStatus !== "COMPLETED" && backgroundJobStatus !== "FAILED") return;
    queryClient.invalidateQueries({ queryKey: queryKeys.jobs.personas(jobId) });
  }, [backgroundJobStatus, jobId, queryClient]);

  return {
    ...query,
    data: Array.isArray(query.data) ? query.data : undefined,
    isPending: query.isPending || (isGenerating && backgroundJobStatus !== "FAILED"),
    isError: query.isError || backgroundJobStatus === "FAILED",
    error:
      backgroundJobStatus === "FAILED"
        ? new Error(backgroundJob.data?.error ?? "Persona generation failed")
        : query.error,
  };
}
