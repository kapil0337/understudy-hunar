import { cn } from "@/lib/utils";
import { humanizeStatus } from "@/lib/status";
import type { components } from "@/lib/api/types";

type Language = components["schemas"]["Language"];

export function LanguageTag({ language, className }: { language: Language; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center rounded-full border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground",
        className,
      )}
    >
      {humanizeStatus(language)}
    </span>
  );
}
