"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { TERMINAL_CALL_STATUSES } from "@/lib/api/schemas";
import { queryKeys } from "./queryKeys";

/** GET /jobs/{id}/board polls itself into a fresh state on every read (the backend refreshes
 * non-terminal outreach rows from Hunar before responding), so client-side polling here is purely
 * about keeping the screen live — 3s while any row is still in flight, otherwise idle. */
export function useBoard(jobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.jobs.board(jobId ?? ""),
    queryFn: ({ signal }) => api.jobs.board(jobId as string, signal),
    enabled: jobId !== undefined,
    refetchInterval: (query) => {
      const rows = query.state.data?.rows;
      if (!rows) return false;
      const hasNonTerminalRow = rows.some(
        (row) => row.status !== null && !TERMINAL_CALL_STATUSES.has(row.status),
      );
      return hasNonTerminalRow ? 3000 : false;
    },
  });
}
