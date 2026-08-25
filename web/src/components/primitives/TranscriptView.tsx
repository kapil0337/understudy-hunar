"use client";

import { useMemo } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Failure, TranscriptTurn } from "@/lib/api/rehearsalScore";
import { METRIC_LABEL } from "@/lib/api/rehearsalScore";

interface TranscriptViewProps {
  turns: TranscriptTurn[];
  /** Matched onto a turn by transcript_excerpt substring — the same excerpt score.py records the
   * failure with, so a turn with no matching excerpt (most efficiency/coverage failures, which
   * carry no excerpt) simply gets no marker rather than a wrong one. */
  failures?: Failure[];
  className?: string;
}

export function TranscriptView({ turns, failures = [], className }: TranscriptViewProps) {
  const failuresByTurn = useMemo(() => {
    const map = new Map<number, Failure[]>();
    for (const turn of turns) {
      const matches = failures.filter(
        (failure) => failure.transcript_excerpt && turn.text.includes(failure.transcript_excerpt),
      );
      if (matches.length > 0) map.set(turn.turn, matches);
    }
    return map;
  }, [turns, failures]);

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {turns.map((turn) => {
        const turnFailures = failuresByTurn.get(turn.turn) ?? [];
        const isAgent = turn.speaker === "agent";

        return (
          <div key={turn.turn} className="flex items-start gap-2">
            <div className="flex w-4 shrink-0 justify-center pt-2.5">
              {turnFailures.length > 0 ? (
                <Tooltip>
                  <TooltipTrigger
                    render={<button type="button" aria-label="Failures on this turn" />}
                  >
                    <span
                      className="block size-2 rounded-full"
                      style={{ backgroundColor: "var(--status-failed)" }}
                    />
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <div className="flex flex-col gap-1">
                      {turnFailures.map((failure, index) => (
                        <span key={index}>
                          {METRIC_LABEL[failure.metric]}: {failure.description}
                        </span>
                      ))}
                    </div>
                  </TooltipContent>
                </Tooltip>
              ) : null}
            </div>
            <div
              className={cn(
                "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                isAgent ? "bg-primary/10" : "ml-auto bg-muted",
              )}
            >
              <div className="mb-0.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
                {turn.speaker}
              </div>
              {turn.text}
            </div>
          </div>
        );
      })}
    </div>
  );
}
