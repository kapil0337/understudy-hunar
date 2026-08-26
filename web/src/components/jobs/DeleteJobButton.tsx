"use client";

import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useDeleteJob } from "@/lib/hooks/useJobs";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

/** A confirm-then-delete affordance for one job row. Deleting is irreversible — it removes the
 * job's candidates, calls, versions, and rehearsal history in the backend too (DELETE /jobs/{id})
 * — so this always confirms first and never fires from a bare click. Used from both the sidebar
 * and the home page's job list, which is why the redirect-away-if-you're-on-it check lives here
 * rather than in either caller. */
export function DeleteJobButton({
  jobId,
  jobTitle,
  className,
}: {
  jobId: string;
  jobTitle: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const deleteJob = useDeleteJob();

  function handleDelete() {
    deleteJob.mutate(jobId, {
      onSuccess: () => {
        setOpen(false);
        toast.add({
          type: "success",
          title: "Job deleted",
          description: `"${jobTitle}" and all its data were removed.`,
        });
        if (pathname.startsWith(`/jobs/${jobId}`)) router.push("/");
      },
    });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon-xs"
            className={cn(
              "shrink-0 text-muted-foreground hover:text-destructive",
              className,
            )}
            aria-label={`Delete ${jobTitle}`}
            onClick={(event) => event.stopPropagation()}
          />
        }
      >
        <Trash2Icon />
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this job?</DialogTitle>
          <DialogDescription>
            This permanently deletes &ldquo;{jobTitle}&rdquo; along with its
            versions, candidates, call history, and rehearsal runs. This
            can&apos;t be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            Cancel
          </DialogClose>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteJob.isPending}
          >
            {deleteJob.isPending ? "Deleting…" : "Delete job"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
