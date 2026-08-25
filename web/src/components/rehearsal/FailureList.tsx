"use client";

import { useState } from "react";
import { EmptyState } from "@/components/primitives/EmptyState";
import { cn } from "@/lib/utils";
import { METRIC_LABEL, type Failure, type Severity } from "@/lib/api/rehearsalScore";

const SEVERITY_VAR: Record<Severity, string> = {
  critical: "failed",
  major: "ringing",
  minor: "not-connected",
};

interface FailureListProps {
  failures: Failure[];
  archetypeByPersonaId: Record<string, string>;
}

/** Backend order is already ranked (severity, then metric weight, descending — see
 * compute_composite in score.py) — this renders that order as-is rather than re-sorting. */
export function FailureList({ failures, archetypeByPersonaId }: FailureListProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  if (failures.length === 0) {
    return <EmptyState title="No failures" description="This run scored cleanly." />;
  }

  return (
    <ul className="flex flex-col gap-1.5">
      {failures.map((failure, index) => {
        const isOpen = expandedIndex === index;
        const varName = SEVERITY_VAR[failure.severity];
        return (
          <li key={index} className="overflow-hidden rounded-md border border-border">
            <button
              type="button"
              onClick={() => setExpandedIndex(isOpen ? null : index)}
              className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-accent/60"
            >
              <span
                aria-hidden="true"
                className="mt-1.5 size-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: `var(--status-${varName})` }}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-[11px] text-muted-foreground">
                  {archetypeByPersonaId[failure.persona_id] ?? "Unknown persona"} ·{" "}
                  {METRIC_LABEL[failure.metric]}
                </span>
                <span>{failure.description}</span>
              </span>
            </button>
            {isOpen && failure.transcript_excerpt ? (
              <div
                className={cn(
                  "border-t border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground italic",
                )}
              >
                &ldquo;{failure.transcript_excerpt}&rdquo;
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
