import { cn } from "@/lib/utils";

interface MetricTileProps {
  label: string;
  value: React.ReactNode;
  sublabel?: React.ReactNode;
  className?: string;
}

export function MetricTile({ label, value, sublabel, className }: MetricTileProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-lg border border-border bg-card px-4 py-3",
        className,
      )}
    >
      <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </span>
      <span className="text-2xl leading-none font-semibold tabular-nums">{value}</span>
      {sublabel ? (
        <span className="text-xs tabular-nums text-muted-foreground">{sublabel}</span>
      ) : null}
    </div>
  );
}
