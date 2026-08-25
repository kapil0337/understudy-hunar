"use client";

import { useState } from "react";
import { TableCell, TableRow } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ScoreBar } from "@/components/primitives/ScoreBar";
import { ConsentBadge } from "@/components/primitives/ConsentBadge";
import { LanguageTag } from "@/components/primitives/LanguageTag";
import { cn } from "@/lib/utils";
import {
  MATCH_COMPONENT_LABEL,
  MATCH_COMPONENT_ORDER,
  matchBreakdownSchema,
} from "@/lib/api/matchBreakdown";
import { usePatchCandidate, useRecordConsent } from "@/lib/hooks/useCandidates";
import type { components } from "@/lib/api/types";

type CandidateRead = components["schemas"]["CandidateRead"];

interface CandidateRowProps {
  jobId: string;
  candidate: CandidateRead;
  selected: boolean;
  onToggleSelect: (checked: boolean) => void;
  /** Set only once a launch attempt has actually refused this candidate — the exact server
   * reason, never a guessed one (the demo allow-list is server-side only, so a lack of consent
   * alone doesn't prove a call would be blocked). */
  blockedReason: string | undefined;
}

export function CandidateRow({
  jobId,
  candidate,
  selected,
  onToggleSelect,
  blockedReason,
}: CandidateRowProps) {
  const [phoneDraft, setPhoneDraft] = useState(candidate.phone_e164 ?? "");
  const [editingPhone, setEditingPhone] = useState(false);
  const patchCandidate = usePatchCandidate(jobId);
  const recordConsent = useRecordConsent(jobId);

  const breakdownResult = candidate.match_breakdown
    ? matchBreakdownSchema.safeParse(candidate.match_breakdown)
    : null;
  const breakdown = breakdownResult?.success ? breakdownResult.data : null;

  const hasPhone = candidate.phone_e164 !== null;
  const isConsented = candidate.consent_recorded_at !== null;

  function savePhone() {
    const trimmed = phoneDraft.trim();
    if (!trimmed || trimmed === candidate.phone_e164) {
      setEditingPhone(false);
      return;
    }
    patchCandidate.mutate(
      { candidateId: candidate.id, body: { phone_e164: trimmed } },
      { onSuccess: () => setEditingPhone(false) },
    );
  }

  return (
    <TableRow className={cn(blockedReason && "opacity-50")}>
      <TableCell>
        <Checkbox
          checked={selected}
          disabled={Boolean(blockedReason)}
          onCheckedChange={(checked) => onToggleSelect(checked === true)}
        />
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-2">
          <span className="font-medium">{candidate.full_name}</span>
          {blockedReason ? (
            <Tooltip>
              <TooltipTrigger render={<span className="text-xs font-medium text-status-failed" />}>
                blocked
              </TooltipTrigger>
              <TooltipContent>{blockedReason}</TooltipContent>
            </Tooltip>
          ) : null}
          {candidate.dnc ? (
            <Tooltip>
              <TooltipTrigger render={<span className="text-xs font-medium text-status-failed" />}>
                DNC
              </TooltipTrigger>
              <TooltipContent>On the do-not-call list.</TooltipContent>
            </Tooltip>
          ) : null}
        </div>
        <div className="text-xs text-muted-foreground">
          {candidate.current_title ?? candidate.headline ?? "—"}
        </div>
      </TableCell>
      <TableCell>
        {breakdown ? (
          <div className="flex flex-col gap-1">
            <ScoreBar
              className="w-28"
              segments={MATCH_COMPONENT_ORDER.map((key) => ({
                key,
                label: MATCH_COMPONENT_LABEL[key],
                score: breakdown.components[key]?.score ?? 0,
                weight: breakdown.components[key]?.weight ?? 0,
              }))}
            />
            <span className="text-xs tabular-nums text-muted-foreground">
              {candidate.match_score !== null ? candidate.match_score.toFixed(0) : "—"}
            </span>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{candidate.location ?? "—"}</TableCell>
      <TableCell>
        {candidate.preferred_language ? (
          <LanguageTag language={candidate.preferred_language} />
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell>
        <ConsentBadge hasPhone={hasPhone} consentRecordedAt={candidate.consent_recorded_at} />
      </TableCell>
      <TableCell>
        {editingPhone ? (
          <div className="flex items-center gap-1">
            <Input
              value={phoneDraft}
              onChange={(event) => setPhoneDraft(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && savePhone()}
              placeholder="+91XXXXXXXXXX"
              className="h-7 w-36 text-xs"
              autoFocus
            />
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2"
              disabled={patchCandidate.isPending}
              onClick={savePhone}
            >
              Save
            </Button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => {
              setPhoneDraft(candidate.phone_e164 ?? "");
              setEditingPhone(true);
            }}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {candidate.phone_e164 ?? "Add phone"}
          </button>
        )}
        {patchCandidate.isError ? (
          <p className="mt-0.5 text-[11px] text-status-failed">{patchCandidate.error.message}</p>
        ) : null}
      </TableCell>
      <TableCell>
        <Checkbox
          checked={isConsented}
          disabled={!hasPhone || isConsented || recordConsent.isPending}
          onCheckedChange={(checked) => {
            if (checked && candidate.phone_e164) {
              recordConsent.mutate({
                candidateId: candidate.id,
                body: { phone_e164: candidate.phone_e164, channel: "MANUAL" },
              });
            }
          }}
        />
      </TableCell>
    </TableRow>
  );
}
