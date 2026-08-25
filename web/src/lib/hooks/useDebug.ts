"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "./queryKeys";

/** Diagnostic only — not part of the product surface (see the "debug" OpenAPI tag). */
export function useWebhookEvents(limit?: number) {
  return useQuery({
    queryKey: queryKeys.debug.webhookEvents(limit),
    queryFn: ({ signal }) => api.debug.listWebhookEvents(limit, signal),
  });
}
