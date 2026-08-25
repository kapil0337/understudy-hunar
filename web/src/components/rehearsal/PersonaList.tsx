"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { METRIC_ORDER, type Failure } from "@/lib/api/rehearsalScore";
import type { components } from "@/lib/api/types";

type PersonaRead = components["schemas"]["PersonaRead"];
type CaseSummary = components["schemas"]["CaseSummary"];

interface PersonaListProps {
  personas: PersonaRead[];
  caseSummaries: CaseSummary[];
  failures: Failure[];
  scoresReady: boolean;
  selectedCaseId: string | undefined;
  onSelect: (caseId: string) => void;
}

/** Six slots, always — a persona whose case hasn't finished simulating yet renders as a
 * skeleton rather than being absent, which is what makes "cases appear as they complete" visible
 * instead of just an initially-short list that silently grows. */
export function PersonaList({
  personas,
  caseSummaries,
  failures,
  scoresReady,
  selectedCaseId,
  onSelect,
}: PersonaListProps) {
  const caseByPersonaId = new Map(caseSummaries.map((c) => [c.persona_id, c]));

  return (
    <ul className="flex flex-col gap-1.5">
      {personas.map((persona) => {
        const rehearsalCase = caseByPersonaId.get(persona.id);

        if (!rehearsalCase) {
          return (
            <li key={persona.id} className="rounded-md border border-border px-3 py-2">
              <div className="mb-1.5 text-sm font-medium text-muted-foreground">
                {persona.archetype}
              </div>
              <Skeleton className="h-3 w-24" />
            </li>
          );
        }

        const isSelected = rehearsalCase.id === selectedCaseId;
        const personaFailures = failures.filter((f) => f.persona_id === persona.id);

        return (
          <li key={persona.id}>
            <button
              type="button"
              onClick={() => onSelect(rehearsalCase.id)}
              className={cn(
                "w-full rounded-md border px-3 py-2 text-left transition-colors",
                isSelected ? "border-primary bg-primary/10" : "border-border hover:bg-accent",
              )}
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">{persona.archetype}</span>
                <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                  {rehearsalCase.turn_count ?? "—"}t ·{" "}
                  {rehearsalCase.estimated_seconds !== null
                    ? `${rehearsalCase.estimated_seconds.toFixed(0)}s`
                    : "—"}
                </span>
              </div>
              <div className="flex gap-1.5">
                {METRIC_ORDER.map((metric) => {
                  const failed = personaFailures.some((f) => f.metric === metric);
                  return (
                    <span
                      key={metric}
                      title={metric}
                      className="size-1.5 rounded-full"
                      style={{
                        backgroundColor: !scoresReady
                          ? "var(--status-queued)"
                          : failed
                            ? "var(--status-failed)"
                            : "var(--status-completed)",
                      }}
                    />
                  );
                })}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
