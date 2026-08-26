"use client";

import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useTheme, type Theme } from "@/components/shell/ThemeProvider";

const OPTIONS: { value: Theme; label: string; icon: typeof SunIcon }[] = [
  { value: "light", label: "Light theme", icon: SunIcon },
  { value: "dark", label: "Dark theme", icon: MoonIcon },
  { value: "system", label: "Match system theme", icon: MonitorIcon },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="flex items-center gap-0.5 rounded-md border border-sidebar-border bg-background/40 p-0.5"
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const selected = theme === value;
        return (
          <Tooltip key={value}>
            <TooltipTrigger
              render={
                <button
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  aria-label={label}
                  onClick={() => setTheme(value)}
                  className={cn(
                    "flex size-6 items-center justify-center rounded transition-colors [&_svg]:size-3.5",
                    selected
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/50 hover:text-sidebar-foreground",
                  )}
                />
              }
            >
              <Icon aria-hidden="true" />
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
