import { cn } from "@/lib/utils";

export type ConsentState = "no-phone" | "phone-added" | "consented";

export function consentState(hasPhone: boolean, consentRecordedAt: string | null): ConsentState {
  if (consentRecordedAt) return "consented";
  if (hasPhone) return "phone-added";
  return "no-phone";
}

const CONFIG: Record<ConsentState, { label: string; varName: string }> = {
  "no-phone": { label: "No phone", varName: "not-connected" },
  "phone-added": { label: "Phone added", varName: "ringing" },
  consented: { label: "Consented", varName: "completed" },
};

interface ConsentBadgeProps {
  hasPhone: boolean;
  consentRecordedAt: string | null;
  className?: string;
}

export function ConsentBadge({ hasPhone, consentRecordedAt, className }: ConsentBadgeProps) {
  const state = consentState(hasPhone, consentRecordedAt);
  const { label, varName } = CONFIG[state];

  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        className,
      )}
      style={{ color: `var(--status-${varName})`, backgroundColor: `var(--status-${varName}-bg)` }}
    >
      <span
        aria-hidden="true"
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: `var(--status-${varName})` }}
      />
      {label}
    </span>
  );
}
