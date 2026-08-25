"use client";

import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, ApiSchemaError } from "@/lib/api/client";
import { Toaster, toast } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";

function shouldRetry(failureCount: number, error: unknown): boolean {
  // A 4xx is the backend telling us the request itself is wrong (bad id, failed validation,
  // unmet consent guard) — retrying won't change that. Only retry transient/server failures.
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

/** The API's own message, never "something went wrong" — every mutation failure surfaces here
 * exactly once, app-wide, so individual mutation calls don't each need their own onError. */
function toastMutationError(error: unknown): void {
  const description =
    error instanceof ApiError || error instanceof ApiSchemaError
      ? error.message
      : error instanceof Error
        ? error.message
        : String(error);
  toast.add({ type: "error", title: "Request failed", description });
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: shouldRetry,
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: false,
          },
        },
        mutationCache: new MutationCache({
          onError: toastMutationError,
        }),
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        {children}
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
