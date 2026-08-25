"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/primitives/ErrorState";
import { useGuardrails } from "@/lib/hooks/useGuardrails";

const DAY_ABBREV: Record<string, string> = {
  MONDAY: "Mon",
  TUESDAY: "Tue",
  WEDNESDAY: "Wed",
  THURSDAY: "Thu",
  FRIDAY: "Fri",
  SATURDAY: "Sat",
  SUNDAY: "Sun",
};

export function GuardrailStrip() {
  const { data: guardrails, isPending, isError, error, refetch } = useGuardrails();

  if (isPending) return <Skeleton className="h-10 w-full" />;
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} className="py-3" />;

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg border border-border bg-card px-4 py-2.5 text-xs">
      <span className="font-medium text-muted-foreground">Calling window</span>
      <span className="tabular-nums">
        {guardrails.allowed_days.map((day) => DAY_ABBREV[day]).join("/")} ·{" "}
        {guardrails.earliest_call_time}–{guardrails.last_call_time} {guardrails.timezone}
      </span>
      <span className="tabular-nums text-muted-foreground">
        Retry up to {guardrails.max_retry_count}× every {guardrails.retry_interval_hours}h
      </span>
      <span
        className="ml-auto inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-medium"
        style={{
          color: guardrails.inside_window_now
            ? "var(--status-completed)"
            : "var(--status-not-connected)",
          backgroundColor: guardrails.inside_window_now
            ? "var(--status-completed-bg)"
            : "var(--status-not-connected-bg)",
        }}
      >
        <span
          aria-hidden="true"
          className="size-1.5 rounded-full"
          style={{
            backgroundColor: guardrails.inside_window_now
              ? "var(--status-completed)"
              : "var(--status-not-connected)",
          }}
        />
        {guardrails.inside_window_now ? "Inside window" : "Outside window"}
      </span>
    </div>
  );
}
