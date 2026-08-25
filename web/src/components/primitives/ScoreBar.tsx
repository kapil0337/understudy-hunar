import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface ScoreBarSegment {
  key: string;
  label: string;
  /** 0-100 */
  score: number;
  /** 0-100, all segments' weights should sum to ~100 */
  weight: number;
}

function scoreColorVar(score: number): string {
  if (score >= 80) return "var(--status-completed)";
  if (score >= 50) return "var(--status-ringing)";
  return "var(--status-failed)";
}

interface ScoreBarProps {
  segments: ScoreBarSegment[];
  className?: string;
}

/** A composite score is never shown without its breakdown (CLAUDE.md) — the bar is always
 * visually segmented by each component's weight; hovering a segment names it and its score. */
export function ScoreBar({ segments, className }: ScoreBarProps) {
  return (
    <div className={cn("flex h-2 w-full gap-px overflow-hidden rounded-full bg-muted", className)}>
      {segments.map((segment) => (
        <Tooltip key={segment.key}>
          <TooltipTrigger
            render={<div />}
            className="relative h-full outline-none"
            style={{ width: `${segment.weight}%` }}
          >
            <div
              className="h-full transition-[width]"
              style={{
                width: `${Math.max(0, Math.min(100, segment.score))}%`,
                backgroundColor: scoreColorVar(segment.score),
              }}
            />
          </TooltipTrigger>
          <TooltipContent>
            {segment.label}: {segment.score.toFixed(0)} · {segment.weight.toFixed(0)}% weight
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}
