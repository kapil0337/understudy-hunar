"use client";

import { StatusPill } from "@/components/primitives/StatusPill";
import { SimulatedBadge } from "@/components/primitives/SimulatedBadge";
import { cn } from "@/lib/utils";
import { humanizeStatus, type StatusBucket } from "@/lib/status";
import type { BoardRow } from "@/lib/api/schemas";

const BUCKET_LABEL: Record<StatusBucket, string> = {
  queued: "Queued",
  ringing: "Ringing",
  "in-progress": "In progress",
  completed: "Completed",
  "not-connected": "Not connected",
  failed: "Failed",
};

interface BoardColumnProps {
  bucket: StatusBucket;
  rows: BoardRow[];
  onSelect: (row: BoardRow) => void;
}

export function BoardColumn({ bucket, rows, onSelect }: BoardColumnProps) {
  return (
    <div className="flex min-w-64 flex-1 flex-col gap-2">
      <div className="flex items-center gap-2 px-1">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {BUCKET_LABEL[bucket]}
        </h3>
        <span className="text-xs tabular-nums text-muted-foreground">{rows.length}</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {rows.map((row) => (
          <button
            key={row.candidate_id}
            type="button"
            onClick={() => onSelect(row)}
            className={cn(
              "flex flex-col gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-left transition-colors hover:bg-accent",
              row.is_simulated && "status-hatch",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium">{row.full_name}</span>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {row.match_score !== null ? row.match_score.toFixed(0) : "—"}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {row.status ? (
                <StatusPill status={row.status} kind="call" />
              ) : (
                <span className="text-xs text-muted-foreground">
                  {humanizeStatus("NOT_STARTED")}
                </span>
              )}
              {row.is_simulated ? <SimulatedBadge /> : null}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
