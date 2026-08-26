"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { DiffView } from "@/components/primitives/DiffView";
import { ErrorState } from "@/components/primitives/ErrorState";
import { useAcceptPatch, useLatestRun, useProposePatch } from "@/lib/hooks/useRuns";
import { useVersion } from "@/lib/hooks/useVersions";
import {
  METRIC_LABEL,
  METRIC_ORDER,
  computeScoreDelta,
  patchRationaleSchema,
  rehearsalScoreSchema,
  type Failure,
  type RehearsalScore,
} from "@/lib/api/rehearsalScore";
import { cn } from "@/lib/utils";

interface PatchPanelProps {
  jobId: string;
  /** Only set once the run is COMPLETED — proposing a fix needs a scored run to work from. */
  runId: string | undefined;
  versionId: string | undefined;
  /** The current run's own scores, parsed — needed to compute the accepted patch's score delta
   * client-side (the accept response has no scores yet; rehearsing the new version is deferred
   * to app/worker.py, see useAcceptPatch). */
  parentScores: RehearsalScore | null;
  /** The run's own failures, in the same ranked order the patcher was shown (top 6) — used to
   * resolve each rationale item's failure_id (a 1-based index, not a database id) back to the
   * failure it addresses. */
  failures: Failure[];
  onAccepted: (result: { versionId: string; runId: string }) => void;
}

export function PatchPanel({
  jobId,
  runId,
  versionId,
  parentScores,
  failures,
  onAccepted,
}: PatchPanelProps) {
  const proposeMutation = useProposePatch();
  const acceptMutation = useAcceptPatch(jobId);
  const { data: version } = useVersion(versionId);

  // Set once accept succeeds — tracks the new version's rehearsal run to completion so the
  // score-delta banner below has something to compare against parentScores.
  const [acceptedVersionId, setAcceptedVersionId] = useState<string | undefined>(undefined);
  const acceptedRunQuery = useLatestRun(acceptedVersionId);
  const acceptedScores = (() => {
    if (!acceptedRunQuery.data?.scores) return null;
    const result = rehearsalScoreSchema.safeParse(acceptedRunQuery.data.scores);
    return result.success ? result.data : null;
  })();
  const scoreDelta =
    parentScores && acceptedScores ? computeScoreDelta(parentScores, acceptedScores) : null;

  const patch = proposeMutation.data;
  const topFailures = failures.slice(0, 6);
  const rationaleResult = patch ? patchRationaleSchema.safeParse(patch.rationale) : null;
  const rationale = rationaleResult?.success ? rationaleResult.data : [];

  return (
    <div className="flex flex-col gap-3 border-t border-border px-6 py-4">
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!runId || proposeMutation.isPending}
          onClick={() => runId && proposeMutation.mutate(runId)}
        >
          {proposeMutation.isPending ? "Proposing fix…" : "Propose fix"}
        </Button>

        {patch ? (
          <Button
            size="sm"
            disabled={acceptMutation.isPending}
            onClick={() =>
              acceptMutation.mutate(patch.id, {
                onSuccess: (result) => {
                  setAcceptedVersionId(result.version.id);
                  onAccepted({ versionId: result.version.id, runId: result.run_id });
                },
              })
            }
          >
            {acceptMutation.isPending ? "Accepting…" : "Accept fix"}
          </Button>
        ) : null}

        {!runId ? (
          <span className="text-xs text-muted-foreground">
            Run this version to completion before proposing a fix.
          </span>
        ) : null}
      </div>

      {proposeMutation.isError ? <ErrorState error={proposeMutation.error} /> : null}
      {acceptMutation.isError ? <ErrorState error={acceptMutation.error} /> : null}

      {patch && version ? (
        <div className="flex flex-col gap-3">
          <div className="max-h-64 overflow-y-auto rounded-lg border border-border bg-card p-3">
            <DiffView before={version.agent_prompt} after={patch.proposed_agent_prompt} />
          </div>
          {rationale.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {rationale.map((item) => {
                const failure = topFailures[Number(item.failure_id) - 1];
                return (
                  <li key={item.failure_id + item.quoted_new_text.slice(0, 16)} className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{item.change_summary}</span>
                    {failure ? ` — addressing: ${failure.description}` : ""}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      ) : null}

      {acceptedVersionId ? (
        <div className="animate-in fade-in slide-in-from-bottom-1 flex flex-wrap items-center gap-3 rounded-md border border-status-completed-bg bg-status-completed-bg px-3 py-2 duration-300">
          {scoreDelta ? (
            <>
              <span className="text-xs font-medium text-status-completed">Re-rehearsed</span>
              {[...METRIC_ORDER, "composite" as const].map((metric) => {
                const delta = scoreDelta[metric];
                if (delta === undefined) return null;
                const positive = delta >= 0;
                return (
                  <span key={metric} className="text-xs tabular-nums">
                    <span className="text-muted-foreground">
                      {metric === "composite" ? "Composite" : METRIC_LABEL[metric]}
                    </span>{" "}
                    <span
                      className={cn(
                        "font-medium",
                        positive ? "text-status-completed" : "text-status-failed",
                      )}
                    >
                      {positive ? "+" : ""}
                      {delta.toFixed(1)}
                    </span>
                  </span>
                );
              })}
            </>
          ) : (
            <span className="text-xs text-muted-foreground">Re-rehearsing the new version…</span>
          )}
        </div>
      ) : null}
    </div>
  );
}
