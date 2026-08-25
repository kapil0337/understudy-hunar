"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { CandidateRow } from "@/components/candidates/CandidateRow";
import { useJobCandidates, useLaunchCalls, useSourceCandidates } from "@/lib/hooks/useCandidates";

export default function CandidatesPage() {
  const { id: jobId } = useParams<{ id: string }>();
  const candidatesQuery = useJobCandidates(jobId);
  const sourceMutation = useSourceCandidates(jobId);
  const launchMutation = useLaunchCalls(jobId);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [blockedReasons, setBlockedReasons] = useState<Record<string, string>>({});

  const candidates = candidatesQuery.data ?? [];
  const selectableIds = candidates.filter((c) => !blockedReasons[c.id]).map((c) => c.id);
  const allSelected = selectableIds.length > 0 && selectedIds.size === selectableIds.length;

  function toggleSelect(id: string, checked: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function toggleSelectAll(checked: boolean) {
    setSelectedIds(checked ? new Set(selectableIds) : new Set());
  }

  function handleCallSelected() {
    const candidateIds = [...selectedIds];
    if (candidateIds.length === 0) return;
    launchMutation.mutate(
      { candidate_ids: candidateIds },
      {
        onSuccess: (result) => {
          if (result.blocked.length > 0) {
            setBlockedReasons((prev) => {
              const next = { ...prev };
              for (const blocked of result.blocked) next[blocked.candidate_id] = blocked.reason;
              return next;
            });
          }
          setSelectedIds(new Set());
        },
      },
    );
  }

  if (candidatesQuery.isPending) {
    return (
      <div className="p-6">
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (candidatesQuery.isError) {
    return (
      <div className="p-6">
        <ErrorState error={candidatesQuery.error} onRetry={() => candidatesQuery.refetch()} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            disabled={sourceMutation.isPending}
            onClick={() => sourceMutation.mutate({ limit: 10 })}
          >
            {sourceMutation.isPending ? "Sourcing…" : "Source candidates"}
          </Button>
          {sourceMutation.data ? (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="rounded-full border border-border px-2 py-0.5">
                {sourceMutation.data.provider}
              </span>
              {sourceMutation.data.cached ? (
                <span className="rounded-full border border-border px-2 py-0.5">cached</span>
              ) : null}
              <span>{sourceMutation.data.candidates.length} found</span>
            </div>
          ) : null}
        </div>
      </div>

      {sourceMutation.isError ? (
        <div className="px-6 pt-4">
          <ErrorState error={sourceMutation.error} />
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {candidates.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title="No candidates yet"
              description="Source candidates above to populate this list."
            />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">
                  <Checkbox
                    checked={allSelected}
                    onCheckedChange={(checked) => toggleSelectAll(checked === true)}
                  />
                </TableHead>
                <TableHead>Candidate</TableHead>
                <TableHead>Match</TableHead>
                <TableHead>Location</TableHead>
                <TableHead>Language</TableHead>
                <TableHead>Reachability</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>Consent</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {candidates.map((candidate) => (
                <CandidateRow
                  key={candidate.id}
                  jobId={jobId}
                  candidate={candidate}
                  selected={selectedIds.has(candidate.id)}
                  onToggleSelect={(checked) => toggleSelect(candidate.id, checked)}
                  blockedReason={blockedReasons[candidate.id]}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {launchMutation.isError ? (
        <div className="px-6 py-2">
          <ErrorState error={launchMutation.error} />
        </div>
      ) : null}

      {selectedIds.size > 0 ? (
        <div className="flex items-center justify-between gap-4 border-t border-border bg-card px-6 py-3">
          <span className="text-sm tabular-nums">{selectedIds.size} selected</span>
          <Button disabled={launchMutation.isPending} onClick={handleCallSelected}>
            {launchMutation.isPending ? "Calling…" : "Call selected"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
