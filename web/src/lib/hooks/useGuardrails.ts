"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "./queryKeys";

/** The org-wide calling window/retry policy (app/services/guardrails.py) — same for every job,
 * so this has no id in its key. `inside_window_now` is computed server-side at request time, so
 * a short poll keeps the board's "inside the window" indicator from going stale across midnight
 * or the window's open/close boundary. */
export function useGuardrails() {
  return useQuery({
    queryKey: queryKeys.guardrails(),
    queryFn: ({ signal }) => api.guardrails.get(signal),
    refetchInterval: 60_000,
  });
}
