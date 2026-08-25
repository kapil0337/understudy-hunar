"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useJob } from "@/lib/hooks/useJobs";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

// Nav order mirrors the assignment's required flow: compile the requirements, rehearse the
// agent against personas before it ever calls anyone, source and prep real candidates, then
// watch the board. Rehearsal sits inside this spine as a step, not a side quest.
const TABS = [
  { segment: "compile", label: "Compile" },
  { segment: "rehearsal", label: "Rehearsal" },
  { segment: "candidates", label: "Candidates" },
  { segment: "board", label: "Board" },
] as const;

export default function JobLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const { data: job, isPending } = useJob(id);

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-col gap-3 border-b border-border px-6 py-4">
        {isPending ? (
          <Skeleton className="h-6 w-64" />
        ) : (
          <h1 className="truncate text-lg font-semibold">{job?.title ?? "Untitled role"}</h1>
        )}

        <nav className="flex gap-1">
          {TABS.map((tab) => {
            const href = `/jobs/${id}/${tab.segment}`;
            const active = pathname.startsWith(href);
            return (
              <Link
                key={tab.segment}
                href={href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-accent-foreground",
                )}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}
