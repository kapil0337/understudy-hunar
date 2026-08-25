"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { useCreateJob, useJobs } from "@/lib/hooks/useJobs";

export default function HomePage() {
  const router = useRouter();
  const jobsQuery = useJobs();
  const createJob = useCreateJob();

  const [title, setTitle] = useState("");
  const [rawJd, setRawJd] = useState("");

  function handleSubmit() {
    if (!title.trim() || !rawJd.trim()) return;
    createJob.mutate(
      { title: title.trim(), raw_jd: rawJd },
      {
        onSuccess: (job) => {
          setTitle("");
          setRawJd("");
          router.push(`/jobs/${job.id}/compile`);
        },
      },
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8 p-8">
      <div>
        <h1 className="text-lg font-semibold">Paste a job description</h1>
        <p className="text-sm text-muted-foreground">
          Understudy compiles it into screening requirements, rehearses an agent against six
          personas, then sources and calls real candidates.
        </p>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder='Role title, e.g. "Delivery Rider — Chennai"'
        />
        <Textarea
          value={rawJd}
          onChange={(event) => setRawJd(event.target.value)}
          placeholder="Paste the full job description…"
          className="min-h-48 font-mono text-sm"
        />
        <div className="flex items-center justify-between gap-4">
          <div className="flex-1">
            {createJob.isError ? <ErrorState error={createJob.error} className="py-2" /> : null}
          </div>
          <Button
            disabled={!title.trim() || !rawJd.trim() || createJob.isPending}
            onClick={handleSubmit}
          >
            {createJob.isPending ? "Creating…" : "Create job"}
          </Button>
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Jobs</h2>
        {jobsQuery.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : jobsQuery.isError ? (
          <ErrorState error={jobsQuery.error} onRetry={() => jobsQuery.refetch()} />
        ) : jobsQuery.data.length === 0 ? (
          <EmptyState
            title="No jobs yet"
            description="Paste a job description above to get started."
          />
        ) : (
          <ul className="flex flex-col gap-1.5">
            {jobsQuery.data.map((job) => (
              <li key={job.id}>
                <Link
                  href={`/jobs/${job.id}/compile`}
                  className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm transition-colors hover:bg-accent"
                >
                  <span className="font-medium">{job.title}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {new Date(job.created_at).toLocaleDateString()}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
