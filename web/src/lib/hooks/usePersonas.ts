"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "./queryKeys";

export function useJobPersonas(jobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.jobs.personas(jobId ?? ""),
    queryFn: ({ signal }) => api.jobs.listPersonas(jobId as string, signal),
    enabled: jobId !== undefined,
  });
}
