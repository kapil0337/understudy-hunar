"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "./queryKeys";

export function useHealthz() {
  return useQuery({
    queryKey: queryKeys.healthz(),
    queryFn: ({ signal }) => api.healthz(signal),
  });
}
