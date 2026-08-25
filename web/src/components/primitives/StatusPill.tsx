import { cn } from "@/lib/utils";
import { callStatusBucket, humanizeStatus, runStatusBucket, type StatusBucket } from "@/lib/status";
import type { CallStatus, RehearsalRunStatus } from "@/lib/api/schemas";

const BUCKET_VAR: Record<StatusBucket, string> = {
  queued: "queued",
  ringing: "ringing",
  "in-progress": "in-progress",
  completed: "completed",
  "not-connected": "not-connected",
  failed: "failed",
};

interface StatusPillProps {
  status: CallStatus | RehearsalRunStatus;
  kind?: "call" | "run";
  className?: string;
}

/** Status is never conveyed by colour alone — the dot carries the bucket colour, the text carries
 * the exact backend status, always. */
export function StatusPill({ status, kind = "call", className }: StatusPillProps) {
  const bucket =
    kind === "run"
      ? runStatusBucket(status as RehearsalRunStatus)
      : callStatusBucket(status as CallStatus);
  const varName = BUCKET_VAR[bucket];

  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        className,
      )}
      style={{
        color: `var(--status-${varName})`,
        backgroundColor: `var(--status-${varName}-bg)`,
      }}
    >
      <span
        aria-hidden="true"
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: `var(--status-${varName})` }}
      />
      {humanizeStatus(status)}
    </span>
  );
}
