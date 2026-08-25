import { CircleAlertIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError, ApiSchemaError } from "@/lib/api/client";

/** The API's own message, never "something went wrong" — ApiError carries the backend's message
 * verbatim, ApiSchemaError names exactly which response shape broke. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof ApiSchemaError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({ error, onRetry, className }: ErrorStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-lg border border-status-failed-bg bg-status-failed-bg px-6 py-12 text-center",
        className,
      )}
    >
      <CircleAlertIcon aria-hidden="true" className="size-6 text-status-failed" />
      <p className="max-w-md text-sm text-status-failed">{errorMessage(error)}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
