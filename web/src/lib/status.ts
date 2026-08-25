import type { CallStatus, RehearsalRunStatus } from "@/lib/api/schemas";

/** The six colour buckets from the design language — every raw backend status maps onto one of
 * these, and each bucket has a matching `--status-*` / `--status-*-bg` CSS var pair (globals.css).
 * Colour is never the only signal: StatusPill always renders the raw status as text too. */
export type StatusBucket =
  | "queued"
  | "ringing"
  | "in-progress"
  | "completed"
  | "not-connected"
  | "failed";

const CALL_STATUS_BUCKET: Record<CallStatus, StatusBucket> = {
  NOT_STARTED: "queued",
  SCHEDULED: "queued",
  INITIATED: "ringing",
  RINGING: "ringing",
  IN_PROGRESS: "in-progress",
  COMPLETED: "completed",
  NOT_CONNECTED: "not-connected",
  CANCELLED: "not-connected",
  FAILED: "failed",
};

const RUN_STATUS_BUCKET: Record<RehearsalRunStatus, StatusBucket> = {
  PENDING: "queued",
  RUNNING: "in-progress",
  COMPLETED: "completed",
  FAILED: "failed",
};

export function callStatusBucket(status: CallStatus): StatusBucket {
  return CALL_STATUS_BUCKET[status];
}

export function runStatusBucket(status: RehearsalRunStatus): StatusBucket {
  return RUN_STATUS_BUCKET[status];
}

/** "NOT_CONNECTED" -> "Not connected". Backend enums are the source of truth for the label text
 * so a new status shows up readable immediately, with no lookup table to keep in sync. */
export function humanizeStatus(status: string): string {
  const lower = status.toLowerCase().replace(/_/g, " ");
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}
