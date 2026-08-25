"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";

type DiffOp = { type: "equal" | "insert" | "delete"; text: string };

/** Word-level LCS diff. Splits on whitespace with a capturing regex so whitespace tokens survive
 * as their own array entries — that's what lets the rendered output keep the original line
 * breaks and spacing instead of collapsing everything onto one line. */
function wordDiff(before: string, after: string): DiffOp[] {
  const a = before.split(/(\s+)/);
  const b = after.split(/(\s+)/);
  const n = a.length;
  const m = b.length;

  const lengths: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lengths[i][j] =
        a[i] === b[j] ? lengths[i + 1][j + 1] + 1 : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    }
  }

  const ops: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: "equal", text: a[i] });
      i += 1;
      j += 1;
    } else if (lengths[i + 1][j] >= lengths[i][j + 1]) {
      ops.push({ type: "delete", text: a[i] });
      i += 1;
    } else {
      ops.push({ type: "insert", text: b[j] });
      j += 1;
    }
  }
  while (i < n) {
    ops.push({ type: "delete", text: a[i] });
    i += 1;
  }
  while (j < m) {
    ops.push({ type: "insert", text: b[j] });
    j += 1;
  }
  return ops;
}

interface DiffViewProps {
  before: string;
  after: string;
  className?: string;
}

export function DiffView({ before, after, className }: DiffViewProps) {
  const ops = useMemo(() => wordDiff(before, after), [before, after]);

  return (
    <pre
      className={cn(
        "font-mono text-xs leading-relaxed whitespace-pre-wrap",
        className,
      )}
    >
      {ops.map((op, index) => {
        if (op.type === "equal") return <span key={index}>{op.text}</span>;
        if (op.type === "delete") {
          return (
            <span
              key={index}
              className="bg-status-failed-bg text-status-failed line-through decoration-1"
            >
              {op.text}
            </span>
          );
        }
        return (
          <span key={index} className="bg-status-completed-bg text-status-completed">
            {op.text}
          </span>
        );
      })}
    </pre>
  );
}
