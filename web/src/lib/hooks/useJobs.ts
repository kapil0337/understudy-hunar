"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/types";
import { useBackgroundJob } from "./useBackgroundJobs";
import { queryKeys } from "./queryKeys";

type JobCreate = components["schemas"]["JobCreate"];
type RequirementsUpdate = components["schemas"]["RequirementsUpdate"];

export function useJobs() {
  return useQuery({
    queryKey: queryKeys.jobs.lists(),
    queryFn: ({ signal }) => api.jobs.list(signal),
  });
}

export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.jobs.detail(jobId ?? ""),
    queryFn: ({ signal }) => api.jobs.get(jobId as string, signal),
    enabled: jobId !== undefined,
  });
}

export function useCreateJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: JobCreate) => api.jobs.create(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.lists() });
    },
  });
}

export function useDeleteJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.jobs.delete(jobId),
    onSuccess: (_data, jobId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.lists() });
      queryClient.removeQueries({ queryKey: queryKeys.jobs.detail(jobId) });
    },
  });
}

/** Compiling is an LLM call, deferred to app/worker.py — the mutation itself only gets back a
 * background_job_id, so this polls that (useBackgroundJob) and invalidates the job + its
 * versions once the compile actually lands, rather than on the immediate 202. Recompiling always
 * creates new draft AgentVersion row(s) — versions are immutable, never edited in place
 * (CONTRIBUTING.md). */
export function useUpdateRequirements(jobId: string) {
  const queryClient = useQueryClient();
  const [backgroundJobId, setBackgroundJobId] = useState<string | undefined>(
    undefined,
  );

  const mutation = useMutation({
    mutationFn: (body: RequirementsUpdate) =>
      api.jobs.updateRequirements(jobId, body),
    onSuccess: (data) => setBackgroundJobId(data.background_job_id),
  });
  const backgroundJob = useBackgroundJob(backgroundJobId);

  useEffect(() => {
    const status = backgroundJob.data?.status;
    if (status !== "COMPLETED" && status !== "FAILED") return;
    queryClient.invalidateQueries({ queryKey: queryKeys.jobs.detail(jobId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.jobs.versions(jobId) });
    setBackgroundJobId(undefined);
  }, [backgroundJob.data?.status, jobId, queryClient]);

  return {
    ...mutation,
    isPending:
      mutation.isPending ||
      backgroundJob.data?.status === "PENDING" ||
      backgroundJob.data?.status === "RUNNING",
    isError: mutation.isError || backgroundJob.data?.status === "FAILED",
    error:
      backgroundJob.data?.status === "FAILED"
        ? new Error(backgroundJob.data.error ?? "Compilation failed")
        : mutation.error,
  };
}
