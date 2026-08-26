"use client";

import { useState } from "react";
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
} from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/primitives/StatusPill";
import { SimulatedBadge } from "@/components/primitives/SimulatedBadge";
import { PredictedComparison } from "@/components/board/PredictedComparison";
import { cn } from "@/lib/utils";
import { useJob } from "@/lib/hooks/useJobs";
import { compiledJdSchema, type KnockoutCriterion } from "@/lib/api/compiledJd";
import type { BoardRow } from "@/lib/api/schemas";

function evaluateKnockout(criterion: KnockoutCriterion, value: unknown): boolean {
  switch (criterion.operator) {
    case "eq":
      return value === criterion.value;
    case "neq":
      return value !== criterion.value;
    case "gte":
      return typeof value === "number" && typeof criterion.value === "number" && value >= criterion.value;
    case "lte":
      return typeof value === "number" && typeof criterion.value === "number" && value <= criterion.value;
    case "gt":
      return typeof value === "number" && typeof criterion.value === "number" && value > criterion.value;
    case "lt":
      return typeof value === "number" && typeof criterion.value === "number" && value < criterion.value;
    case "in":
      return Array.isArray(criterion.value) && typeof value === "string" && criterion.value.includes(value);
    case "not_in":
      return (
        Array.isArray(criterion.value) && typeof value === "string" && !criterion.value.includes(value)
      );
    default:
      return false;
  }
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
}

interface CandidateDrawerProps {
  jobId: string;
  row: BoardRow | null;
  onClose: () => void;
}

export function CandidateDrawer({ jobId, row, onClose }: CandidateDrawerProps) {
  const [showRaw, setShowRaw] = useState(false);
  const jobQuery = useJob(jobId);

  const compiledResult = jobQuery.data?.compiled
    ? compiledJdSchema.safeParse(jobQuery.data.compiled)
    : null;
  const compiled = compiledResult?.success ? compiledResult.data : null;

  const questionText = new Map(
    (compiled?.screening_questions ?? []).map((question) => [question.id, question.text]),
  );
  const knockoutsByQuestion = new Map<string, KnockoutCriterion[]>();
  for (const criterion of compiled?.knockout_criteria ?? []) {
    const list = knockoutsByQuestion.get(criterion.question_id) ?? [];
    list.push(criterion);
    knockoutsByQuestion.set(criterion.question_id, list);
  }

  const result = row?.result ?? null;
  const resultEntries = result ? Object.entries(result) : [];

  return (
    <Drawer
      open={row !== null}
      onOpenChange={(open) => !open && onClose()}
      swipeDirection="right"
    >
      <DrawerContent className="sm:[--drawer-content-width:30rem]">
        {row ? (
          <>
            <DrawerHeader>
              <DrawerTitle>{row.full_name}</DrawerTitle>
              <DrawerDescription>
                {row.phone_e164 ?? "No phone on file"}
                {row.match_score !== null ? ` · match ${row.match_score.toFixed(0)}` : ""}
              </DrawerDescription>
            </DrawerHeader>

            <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 pb-6">
              <div className="flex flex-wrap items-center gap-2" data-testid="outreach-status-row">
                {row.status ? <StatusPill status={row.status} kind="call" /> : null}
                {row.is_simulated ? <SimulatedBadge /> : null}
                {row.lifecycle_status ? (
                  <span className="text-xs text-muted-foreground">{row.lifecycle_status}</span>
                ) : null}
                <span className="text-xs tabular-nums text-muted-foreground">
                  {formatDuration(row.duration_seconds)}
                </span>
              </div>

              {row.call_summary ? (
                <p className="text-sm text-muted-foreground">{row.call_summary}</p>
              ) : null}

              {row.recording_url ? (
                <div>
                  <h3 className="mb-1.5 text-xs font-medium text-muted-foreground">Recording</h3>
                  <audio controls src={row.recording_url} className="w-full" />
                </div>
              ) : null}

              <div>
                <h3 className="mb-1.5 text-xs font-medium text-muted-foreground">Result</h3>
                {resultEntries.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No result recorded yet.</p>
                ) : (
                  <ul className="flex flex-col gap-1.5">
                    {resultEntries.map(([field, value]) => {
                      const knockouts = knockoutsByQuestion.get(field) ?? [];
                      const triggered = knockouts.some((criterion) => evaluateKnockout(criterion, value));
                      return (
                        <li
                          key={field}
                          className={cn(
                            "rounded-md border px-2.5 py-1.5 text-sm",
                            triggered
                              ? "border-status-failed-bg bg-status-failed-bg"
                              : "border-border",
                          )}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs text-muted-foreground">
                              {questionText.get(field) ?? field}
                            </span>
                            {knockouts.length > 0 ? (
                              <span
                                className={cn(
                                  "text-[10px] font-medium tracking-wide uppercase",
                                  triggered ? "text-status-failed" : "text-muted-foreground",
                                )}
                              >
                                knockout{triggered ? " · triggered" : ""}
                              </span>
                            ) : null}
                          </div>
                          <span className={cn(triggered && "text-status-failed")}>
                            {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              {row.agent_version_id && result ? (
                <div>
                  <h3 className="mb-1.5 text-xs font-medium text-muted-foreground">
                    Rehearsal prediction
                  </h3>
                  <PredictedComparison agentVersionId={row.agent_version_id} realResult={result} />
                </div>
              ) : null}

              <div>
                <Button variant="outline" size="sm" onClick={() => setShowRaw((prev) => !prev)}>
                  {showRaw ? "Hide raw JSON" : "Show raw JSON"}
                </Button>
                {showRaw ? (
                  <pre className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-border bg-card p-3 font-mono text-xs whitespace-pre-wrap">
                    {JSON.stringify(row, null, 2)}
                  </pre>
                ) : null}
              </div>
            </div>
          </>
        ) : null}
      </DrawerContent>
    </Drawer>
  );
}
