"use client";

import { useQueries } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/hooks/queryKeys";
import { useLatestRun } from "@/lib/hooks/useRuns";
import { Skeleton } from "@/components/ui/skeleton";
import { SimulatedBadge } from "@/components/primitives/SimulatedBadge";

/** Fraction of `real`'s own keys that also appear, with an equal (stringified) value, in
 * `ground_truth` — a simple, explainable stand-in for "how close is this persona" since there is
 * no other link between a real candidate and a synthetic persona to compare against. */
function similarity(real: Record<string, unknown>, groundTruth: Record<string, unknown>): number {
  const keys = Object.keys(real);
  if (keys.length === 0) return 0;
  const matches = keys.filter((key) => String(real[key]) === String(groundTruth[key])).length;
  return matches / keys.length;
}

interface PredictedComparisonProps {
  agentVersionId: string;
  realResult: Record<string, unknown>;
}

/** Beside the real result, what the closest rehearsed persona's simulated call predicted for the
 * same fields — "closest" by matching the real result against each persona's ground truth. */
export function PredictedComparison({ agentVersionId, realResult }: PredictedComparisonProps) {
  const runQuery = useLatestRun(agentVersionId);
  const run = runQuery.data;
  const caseSummaries = run?.case_summaries ?? [];

  const caseQueries = useQueries({
    queries: caseSummaries.map((summary) => ({
      queryKey: queryKeys.runs.case(run?.id ?? "", summary.id),
      queryFn: () => api.runs.getCase(run?.id ?? "", summary.id),
      enabled: run !== undefined,
    })),
  });

  if (runQuery.isPending || caseQueries.some((query) => query.isPending)) {
    return <Skeleton className="h-20 w-full" />;
  }

  if (!run) {
    return (
      <p className="text-xs text-muted-foreground">
        This version has never been rehearsed — nothing to compare against.
      </p>
    );
  }

  const loadedCases = caseSummaries
    .map((summary, index) => ({ summary, data: caseQueries[index]?.data }))
    .filter(
      (entry): entry is { summary: (typeof caseSummaries)[number]; data: NonNullable<typeof entry.data> } =>
        entry.data !== undefined,
    );

  if (loadedCases.length === 0) {
    return <p className="text-xs text-muted-foreground">No rehearsal cases to compare against.</p>;
  }

  let closest = loadedCases[0];
  let bestScore = -1;
  for (const entry of loadedCases) {
    const score = similarity(realResult, entry.data.ground_truth);
    if (score > bestScore) {
      bestScore = score;
      closest = entry;
    }
  }

  const keys = Object.keys(realResult);
  const predicted = closest.data.extracted_result ?? {};

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <SimulatedBadge />
        <span className="text-xs text-muted-foreground">
          closest archetype: <span className="font-medium text-foreground">{closest.summary.archetype}</span>
        </span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-1 font-medium">Field</th>
            <th className="py-1 font-medium">Real</th>
            <th className="py-1 font-medium">Predicted</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key} className="border-b border-border/50">
              <td className="py-1 pr-2 font-medium">{key}</td>
              <td className="py-1 pr-2 tabular-nums">{String(realResult[key])}</td>
              <td className="py-1 tabular-nums text-muted-foreground">
                {key in predicted ? String(predicted[key]) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
