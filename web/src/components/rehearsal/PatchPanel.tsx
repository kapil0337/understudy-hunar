"use client";

import { Button } from "@/components/ui/button";
import { DiffView } from "@/components/primitives/DiffView";
import { ErrorState } from "@/components/primitives/ErrorState";
import { useAcceptPatch, useProposePatch } from "@/lib/hooks/useRuns";
import { useVersion } from "@/lib/hooks/useVersions";
import { METRIC_LABEL, METRIC_ORDER, patchRationaleSchema, type Failure } from "@/lib/api/rehearsalScore";
import { cn } from "@/lib/utils";

interface PatchPanelProps {
  jobId: string;
  /** Only set once the run is COMPLETED — proposing a fix needs a scored run to work from. */
  runId: string | undefined;
  versionId: string | undefined;
  /** The run's own failures, in the same ranked order the patcher was shown (top 6) — used to
   * resolve each rationale item's failure_id (a 1-based index, not a database id) back to the
   * failure it addresses. */
  failures: Failure[];
  onAccepted: (result: { versionId: string; runId: string }) => void;
}

export function PatchPanel({ jobId, runId, versionId, failures, onAccepted }: PatchPanelProps) {
  const proposeMutation = useProposePatch();
  const acceptMutation = useAcceptPatch(jobId);
  const { data: version } = useVersion(versionId);

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
                onSuccess: (result) =>
                  onAccepted({ versionId: result.version.id, runId: result.run.id }),
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

      {acceptMutation.data ? (
        <div className="animate-in fade-in slide-in-from-bottom-1 flex flex-wrap items-center gap-3 rounded-md border border-status-completed-bg bg-status-completed-bg px-3 py-2 duration-300">
          <span className="text-xs font-medium text-status-completed">
            v{acceptMutation.data.version.version_no} re-rehearsed
          </span>
          {[...METRIC_ORDER, "composite" as const].map((metric) => {
            const delta = acceptMutation.data.score_delta[metric];
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
        </div>
      ) : null}
    </div>
  );
}
