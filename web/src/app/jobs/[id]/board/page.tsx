"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { MetricTile } from "@/components/primitives/MetricTile";
import { GuardrailStrip } from "@/components/board/GuardrailStrip";
import { BoardColumn } from "@/components/board/BoardColumn";
import { CandidateDrawer } from "@/components/board/CandidateDrawer";
import { useBoard } from "@/lib/hooks/useBoard";
import { callStatusBucket, type StatusBucket } from "@/lib/status";
import type { BoardRow } from "@/lib/api/schemas";

const COLUMN_ORDER: StatusBucket[] = [
  "queued",
  "ringing",
  "in-progress",
  "completed",
  "not-connected",
  "failed",
];

function formatAvgDuration(rows: BoardRow[]): string {
  const durations = rows.map((r) => r.duration_seconds).filter((d): d is number => d !== null);
  if (durations.length === 0) return "—";
  const avg = durations.reduce((sum, d) => sum + d, 0) / durations.length;
  const minutes = Math.floor(avg / 60);
  const seconds = Math.round(avg % 60);
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

export default function BoardPage() {
  const { id: jobId } = useParams<{ id: string }>();
  const boardQuery = useBoard(jobId);
  const [selectedRow, setSelectedRow] = useState<BoardRow | null>(null);

  const rows = useMemo(() => boardQuery.data?.rows ?? [], [boardQuery.data]);

  const rowsByBucket = useMemo(() => {
    const map = new Map<StatusBucket, BoardRow[]>(COLUMN_ORDER.map((bucket) => [bucket, []]));
    for (const row of rows) {
      const bucket = row.status ? callStatusBucket(row.status) : "queued";
      map.get(bucket)?.push(row);
    }
    return map;
  }, [rows]);

  const metrics = useMemo(() => {
    const dialled = rows.filter((r) => r.status !== null).length;
    const connected = rows.filter((r) => r.status === "IN_PROGRESS" || r.status === "COMPLETED").length;
    const qualified = rows.filter(
      (r) => r.result !== null && r.result.qualified === true,
    ).length;
    const connectRate = dialled > 0 ? (connected / dialled) * 100 : 0;
    return { dialled, connected, qualified, connectRate };
  }, [rows]);

  if (boardQuery.isPending) {
    return (
      <div className="p-6">
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (boardQuery.isError) {
    return (
      <div className="p-6">
        <ErrorState error={boardQuery.error} onRetry={() => boardQuery.refetch()} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <MetricTile label="Dialled" value={metrics.dialled} />
        <MetricTile label="Connected" value={metrics.connected} />
        <MetricTile label="Connect rate" value={`${metrics.connectRate.toFixed(0)}%`} />
        <MetricTile label="Qualified" value={metrics.qualified} />
        <MetricTile label="Avg duration" value={formatAvgDuration(rows)} />
      </div>

      <GuardrailStrip />

      {rows.length === 0 ? (
        <EmptyState
          title="No candidates on the board"
          description="Source candidates and launch calls from the Candidates tab to populate this board."
        />
      ) : (
        <div className="flex flex-1 gap-4 overflow-x-auto pb-2">
          {COLUMN_ORDER.map((bucket) => (
            <BoardColumn
              key={bucket}
              bucket={bucket}
              rows={rowsByBucket.get(bucket) ?? []}
              onSelect={setSelectedRow}
            />
          ))}
        </div>
      )}

      <CandidateDrawer jobId={jobId} row={selectedRow} onClose={() => setSelectedRow(null)} />
    </div>
  );
}
