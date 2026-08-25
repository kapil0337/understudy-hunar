import { cn } from "@/lib/utils";

/** Marks rehearsal-origin content (a persona transcript, a simulated result) so it is never
 * mistaken for a real call — the diagonal hatch (.status-hatch, globals.css) is the one piece of
 * texture in the design language that survives greyscale/colourblind viewing, on top of the text
 * label every status pill already carries. */
export function SimulatedBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "status-hatch inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        className,
      )}
      style={{ color: "var(--status-simulated)" }}
    >
      Simulated
    </span>
  );
}
