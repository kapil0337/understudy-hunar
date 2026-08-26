"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useJobs } from "@/lib/hooks/useJobs";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { DeleteJobButton } from "@/components/jobs/DeleteJobButton";
import { ThemeToggle } from "@/components/shell/ThemeToggle";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: jobs, isPending, isError } = useJobs();

  return (
    <div className="flex h-dvh w-full overflow-hidden">
      <aside className="flex w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
        <Link
          href="/"
          className="border-b border-sidebar-border px-4 py-4 text-sm font-semibold tracking-tight"
        >
          Understudy
        </Link>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          <div className="px-2 pb-1.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            Jobs
          </div>

          {isPending ? (
            <div className="flex flex-col gap-1 px-2">
              <Skeleton className="h-7 w-full" />
              <Skeleton className="h-7 w-full" />
              <Skeleton className="h-7 w-full" />
            </div>
          ) : isError ? (
            <p className="px-2 py-1 text-xs text-muted-foreground">
              Couldn&apos;t load jobs
            </p>
          ) : jobs.length === 0 ? (
            <p className="px-2 py-1 text-xs text-muted-foreground">
              No jobs yet
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {jobs.map((job) => {
                const active = pathname.startsWith(`/jobs/${job.id}`);
                return (
                  <li key={job.id} className="group flex items-center gap-0.5">
                    <Link
                      href={`/jobs/${job.id}/compile`}
                      title={job.title}
                      className={cn(
                        "block min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-sm transition-colors",
                        active
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                      )}
                    >
                      {job.title}
                    </Link>
                    <DeleteJobButton
                      jobId={job.id}
                      jobTitle={job.title}
                      className="opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </nav>

        <div className="flex items-center justify-between gap-2 border-t border-sidebar-border px-2 py-2">
          <Link
            href="/debug"
            className={cn(
              "rounded-md px-2 py-1.5 text-xs transition-colors",
              pathname === "/debug"
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-muted-foreground hover:bg-sidebar-accent/60",
            )}
          >
            Debug
          </Link>
          <ThemeToggle />
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
