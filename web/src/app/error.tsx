"use client";

import { ErrorState } from "@/components/primitives/ErrorState";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <ErrorState error={error} onRetry={reset} className="max-w-lg" />
    </div>
  );
}
