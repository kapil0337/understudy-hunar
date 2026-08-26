"use client";

import { useState } from "react";
import { PlusIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface FactsListProps {
  values: string[];
  onChange: (values: string[]) => void;
}

/** facts_the_agent_may_state — the whole faithfulness contract (CONTRIBUTING.md: anything the agent
 * says beyond this list is a fabrication at scoring time), so each fact is a full sentence, one
 * per line, not a short chip. */
export function FactsList({ values, onChange }: FactsListProps) {
  const [draft, setDraft] = useState("");

  function add() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onChange([...values, trimmed]);
    setDraft("");
  }

  return (
    <div className="flex flex-col gap-1.5">
      <ul className="flex flex-col gap-1">
        {values.map((value, index) => (
          <li
            key={index}
            className="flex items-start gap-2 rounded-md border border-border px-2 py-1.5 text-sm"
          >
            <span className="flex-1">{value}</span>
            <button
              type="button"
              onClick={() => onChange(values.filter((_, i) => i !== index))}
              aria-label="Remove fact"
              className="mt-0.5 text-muted-foreground hover:text-foreground"
            >
              <XIcon className="size-3.5" />
            </button>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-2">
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
          placeholder="Add a fact the agent may state…"
          className="h-8 flex-1 text-sm"
        />
        <Button type="button" variant="outline" size="sm" onClick={add}>
          <PlusIcon className="size-3.5" />
          Add
        </Button>
      </div>
    </div>
  );
}
