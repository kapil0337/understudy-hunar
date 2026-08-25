"use client";

import { z } from "zod";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { TranscriptView } from "@/components/primitives/TranscriptView";
import { cn } from "@/lib/utils";
import { useCase } from "@/lib/hooks/useRuns";
import { caseMetricsSchema, transcriptTurnSchema, type Failure } from "@/lib/api/rehearsalScore";

const transcriptSchema = z.array(transcriptTurnSchema);

interface CaseDetailProps {
  runId: string | undefined;
  caseId: string | undefined;
  archetype: string | undefined;
  runFailures: Failure[];
}

export function CaseDetail({ runId, caseId, archetype, runFailures }: CaseDetailProps) {
  const { data: caseRead, isPending, isError, error, refetch } = useCase(runId, caseId);

  if (!runId || !caseId) {
    return (
      <EmptyState
        title="No persona selected"
        description="Run this version, then pick a persona on the left as its case completes."
      />
    );
  }

  if (isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-16 w-3/4" />
        <Skeleton className="ml-auto h-16 w-3/4" />
        <Skeleton className="h-16 w-2/3" />
      </div>
    );
  }

  if (isError) {
    return <ErrorState error={error} onRetry={() => refetch()} />;
  }

  const transcriptResult = transcriptSchema.safeParse(caseRead.transcript ?? []);
  const turns = transcriptResult.success ? transcriptResult.data : [];
  const personaFailures = runFailures.filter((f) => f.persona_id === caseRead.persona_id);

  const metricsResult = caseMetricsSchema.safeParse(caseRead.metrics);
  const fields = metricsResult.success ? metricsResult.data.extraction_accuracy.fields : null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h3 className="mb-2 text-sm font-medium text-muted-foreground">{archetype}</h3>
        {turns.length === 0 ? (
          <p className="text-sm text-muted-foreground">No transcript recorded for this case.</p>
        ) : (
          <TranscriptView turns={turns} failures={personaFailures} />
        )}
      </div>

      <div>
        <h3 className="mb-2 text-sm font-medium text-muted-foreground">
          Extracted vs. ground truth
        </h3>
        {fields === null ? (
          <p className="text-sm text-muted-foreground">
            Scoring isn&apos;t complete for this run yet.
          </p>
        ) : fields.length === 0 ? (
          <p className="text-sm text-muted-foreground">No screening fields to compare.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="py-1 font-medium">Field</th>
                <th className="py-1 font-medium">Expected</th>
                <th className="py-1 font-medium">Extracted</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr
                  key={field.field}
                  className={cn(
                    "border-b border-border/60",
                    !field.correct && "bg-status-failed-bg",
                  )}
                >
                  <td className="py-1.5 pr-3 font-medium">{field.field}</td>
                  <td
                    className={cn(
                      "py-1.5 pr-3 tabular-nums",
                      !field.correct && "text-status-failed",
                    )}
                  >
                    {String(field.expected)}
                  </td>
                  <td className={cn("py-1.5 tabular-nums", !field.correct && "text-status-failed")}>
                    {String(field.actual)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
