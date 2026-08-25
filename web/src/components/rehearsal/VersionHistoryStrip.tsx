"use client";

import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/types";

type VersionHistoryRow = components["schemas"]["VersionHistoryRow"];

interface VersionHistoryStripProps {
  versions: VersionHistoryRow[];
  selectedVersionId: string | undefined;
  onSelect: (versionId: string) => void;
}

export function VersionHistoryStrip({
  versions,
  selectedVersionId,
  onSelect,
}: VersionHistoryStripProps) {
  return (
    <div className="flex items-center gap-2 overflow-x-auto border-t border-border px-6 py-3">
      {versions.map((version) => {
        const active = version.id === selectedVersionId;
        return (
          <button
            key={version.id}
            type="button"
            onClick={() => onSelect(version.id)}
            className={cn(
              "flex shrink-0 flex-col items-center gap-0.5 rounded-md border px-3 py-1.5 text-xs transition-colors",
              active ? "border-primary bg-primary/10" : "border-border hover:bg-accent",
            )}
          >
            <span className="font-medium">v{version.version_no}</span>
            <span className="tabular-nums text-muted-foreground">
              {version.latest_composite_score !== null
                ? version.latest_composite_score.toFixed(0)
                : "—"}
            </span>
          </button>
        );
      })}
    </div>
  );
}
