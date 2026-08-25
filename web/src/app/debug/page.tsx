"use client";

import { useState } from "react";
import { CheckIcon, XIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { useWebhookEvents } from "@/lib/hooks/useDebug";

export default function DebugPage() {
  const eventsQuery = useWebhookEvents(50);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (eventsQuery.isPending) {
    return (
      <div className="p-6">
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (eventsQuery.isError) {
    return (
      <div className="p-6">
        <ErrorState error={eventsQuery.error} onRetry={() => eventsQuery.refetch()} />
      </div>
    );
  }

  const events = eventsQuery.data;

  return (
    <div className="flex flex-col gap-4 p-6">
      <div>
        <h1 className="text-lg font-semibold">Webhook feed</h1>
        <p className="text-sm text-muted-foreground">
          Every inbound Hunar webhook, valid or not — diagnostic only, not part of the product
          surface.
        </p>
      </div>

      {events.length === 0 ? (
        <EmptyState
          title="No webhook events yet"
          description="Nothing has arrived from Hunar for this deployment."
        />
      ) : (
        <ul className="flex flex-col gap-1.5">
          {events.map((event) => {
            const isOpen = expandedId === event.id;
            return (
              <li key={event.id} className="overflow-hidden rounded-md border border-border">
                <button
                  type="button"
                  onClick={() => setExpandedId(isOpen ? null : event.id)}
                  className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-accent/60"
                >
                  {event.signature_valid ? (
                    <CheckIcon
                      aria-label="Signature valid"
                      className="size-4 shrink-0 text-status-completed"
                    />
                  ) : (
                    <XIcon
                      aria-label="Signature invalid"
                      className="size-4 shrink-0 text-status-failed"
                    />
                  )}
                  <span className="font-medium">{event.event_type}</span>
                  {event.call_id ? (
                    <span className="text-xs text-muted-foreground">call {event.call_id}</span>
                  ) : null}
                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                    {new Date(event.received_at).toLocaleString()}
                  </span>
                </button>
                {isOpen ? (
                  <pre className="max-h-64 overflow-y-auto border-t border-border bg-card p-3 font-mono text-xs whitespace-pre-wrap">
                    {JSON.stringify(event.raw_payload, null, 2)}
                  </pre>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
