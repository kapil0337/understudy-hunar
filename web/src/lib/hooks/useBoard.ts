"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { TERMINAL_CALL_STATUSES, type BoardRow } from "@/lib/api/schemas";
import { queryKeys } from "./queryKeys";

/** True while any row still has a call in flight — a null status (never called) is not "in
 * flight", it's simply nothing to poll for. Exported (not inlined into refetchInterval) so it has
 * a unit test independent of mocking react-query's polling internals. */
export function hasNonTerminalRow(rows: BoardRow[]): boolean {
  return rows.some((row) => row.status !== null && !TERMINAL_CALL_STATUSES.has(row.status));
}

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
      return hasNonTerminalRow(rows) ? 3000 : false;
    },
  });
}
