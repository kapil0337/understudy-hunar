"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { ScoreBar } from "@/components/primitives/ScoreBar";
import { StatusPill } from "@/components/primitives/StatusPill";
import { CaseDetail } from "@/components/rehearsal/CaseDetail";
import { FailureList } from "@/components/rehearsal/FailureList";
import { PatchPanel } from "@/components/rehearsal/PatchPanel";
import { PersonaList } from "@/components/rehearsal/PersonaList";
import { VersionHistoryStrip } from "@/components/rehearsal/VersionHistoryStrip";
import { useJobPersonas } from "@/lib/hooks/usePersonas";
import { useLatestRun } from "@/lib/hooks/useRuns";
import { useJobVersions, useRehearseVersion } from "@/lib/hooks/useVersions";
import { METRIC_LABEL, METRIC_ORDER, METRIC_WEIGHT, rehearsalScoreSchema } from "@/lib/api/rehearsalScore";

export default function RehearsalPage() {
  const { id: jobId } = useParams<{ id: string }>();

  const versionsQuery = useJobVersions(jobId);
  const personasQuery = useJobPersonas(jobId);
  const rehearseMutation = useRehearseVersion(jobId);

  const [selectedVersionId, setSelectedVersionId] = useState<string | undefined>(undefined);
  const [selectedCaseId, setSelectedCaseId] = useState<string | undefined>(undefined);

  const versions = versionsQuery.data;

  // Default to the most recently created version once versions load, and re-pick if the
  // currently selected one disappears (there is no delete route today, but accepting a patch
  // adds a new one, so this also keeps the selection valid after that).
  useEffect(() => {
    if (!versions || versions.length === 0) return;
    if (selectedVersionId && versions.some((v) => v.id === selectedVersionId)) return;
    setSelectedVersionId(versions[versions.length - 1].id);
  }, [versions, selectedVersionId]);

  const runQuery = useLatestRun(selectedVersionId);
  const run = runQuery.data;

  useEffect(() => {
    setSelectedCaseId(undefined);
  }, [selectedVersionId]);

  useEffect(() => {
    if (!run || run.case_summaries.length === 0) return;
    if (selectedCaseId && run.case_summaries.some((c) => c.id === selectedCaseId)) return;
    setSelectedCaseId(run.case_summaries[0].id);
  }, [run, selectedCaseId]);

  const scores = useMemo(() => {
    if (!run?.scores) return null;
    const result = rehearsalScoreSchema.safeParse(run.scores);
    return result.success ? result.data : null;
  }, [run?.scores]);

  const personas = useMemo(() => personasQuery.data ?? [], [personasQuery.data]);
  const archetypeByPersonaId = useMemo(
    () => Object.fromEntries(personas.map((persona) => [persona.id, persona.archetype])),
    [personas],
  );
  const selectedCase = run?.case_summaries.find((c) => c.id === selectedCaseId);
  const isRunInFlight = run?.status === "PENDING" || run?.status === "RUNNING";

  if (versionsQuery.isPending) {
    return (
      <div className="p-6">
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (versionsQuery.isError) {
    return (
      <div className="p-6">
        <ErrorState error={versionsQuery.error} onRetry={() => versionsQuery.refetch()} />
      </div>
    );
  }

  if (!versions || versions.length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          title="No versions yet"
          description="Compile this job's requirements first — that's what creates the draft version this screen rehearses."
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-col gap-4 border-b border-border px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Select
            value={selectedVersionId}
            onValueChange={(value) => setSelectedVersionId(value ?? undefined)}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="Select a version" />
            </SelectTrigger>
            <SelectContent>
              {versions.map((version) => (
                <SelectItem key={version.id} value={version.id}>
                  v{version.version_no} · {version.language} ·{" "}
                  {version.origin === "PATCHED" ? "patched" : "compiled"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            disabled={!selectedVersionId || rehearseMutation.isPending || isRunInFlight}
            onClick={() => selectedVersionId && rehearseMutation.mutate(selectedVersionId)}
          >
            {isRunInFlight ? "Running…" : "Run"}
          </Button>
        </div>

        {runQuery.isPending ? (
          <Skeleton className="h-16 w-full max-w-md" />
        ) : runQuery.isError ? (
          <ErrorState error={runQuery.error} onRetry={() => runQuery.refetch()} />
        ) : !run ? (
          <EmptyState
            title="Never rehearsed"
            description="Click Run to rehearse this version against its six personas."
          />
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-4">
              <span className="text-4xl leading-none font-semibold tabular-nums">
                {scores ? scores.composite.toFixed(0) : "—"}
              </span>
              <StatusPill status={run.status} kind="run" />
              <span className="text-xs tabular-nums text-muted-foreground">
                {run.llm_calls} LLM calls · {run.cached_calls} cached
              </span>
            </div>
            {scores ? (
              <ScoreBar
                className="max-w-md"
                segments={METRIC_ORDER.map((metric) => ({
                  key: metric,
                  label: METRIC_LABEL[metric],
                  score: scores[metric].score,
                  weight: METRIC_WEIGHT[metric],
                }))}
              />
            ) : null}
          </div>
        )}
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[260px_1fr_300px] divide-x divide-border">
        <div className="overflow-y-auto p-3">
          {personasQuery.isPending ? (
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : personasQuery.isError ? (
            <ErrorState error={personasQuery.error} onRetry={() => personasQuery.refetch()} />
          ) : (
            <PersonaList
              personas={personas}
              caseSummaries={run?.case_summaries ?? []}
              failures={scores?.failures ?? []}
              scoresReady={scores !== null}
              selectedCaseId={selectedCaseId}
              onSelect={setSelectedCaseId}
            />
          )}
        </div>

        <div className="overflow-y-auto p-4">
          <CaseDetail
            runId={run?.id}
            caseId={selectedCaseId}
            archetype={selectedCase ? archetypeByPersonaId[selectedCase.persona_id] : undefined}
            runFailures={scores?.failures ?? []}
          />
        </div>

        <div className="overflow-y-auto p-3">
          <FailureList
            failures={scores?.failures ?? []}
            archetypeByPersonaId={archetypeByPersonaId}
          />
        </div>
      </div>

      {run ? (
        <PatchPanel
          jobId={jobId}
          runId={run.status === "COMPLETED" ? run.id : undefined}
          versionId={selectedVersionId}
          failures={scores?.failures ?? []}
          onAccepted={({ versionId }) => setSelectedVersionId(versionId)}
        />
      ) : null}

      <VersionHistoryStrip
        versions={versions}
        selectedVersionId={selectedVersionId}
        onSelect={setSelectedVersionId}
      />
    </div>
  );
}
