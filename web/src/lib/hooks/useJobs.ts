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

/** Recompiling always creates new draft AgentVersion row(s) — invalidate versions alongside the
 * job itself (CLAUDE.md: versions are immutable, never edited in place). */
export function useUpdateRequirements(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RequirementsUpdate) => api.jobs.updateRequirements(jobId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.detail(jobId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.versions(jobId) });
    },
  });
}
