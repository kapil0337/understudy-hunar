"use client";

import { ChevronDownIcon, ChevronUpIcon, PlusIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ScreeningQuestion } from "@/lib/api/compiledJd";

interface QuestionsEditorProps {
  questions: ScreeningQuestion[];
  onChange: (questions: ScreeningQuestion[]) => void;
}

/** Order and wording are editable; answer_type/options/why_it_matters render read-only — they
 * shape knockout_criteria and result_schema elsewhere in the compiled JD, so changing them here
 * without touching those too would silently desync the preview from what recompiling would
 * actually produce. */
export function QuestionsEditor({ questions, onChange }: QuestionsEditorProps) {
  function update(index: number, text: string) {
    onChange(questions.map((question, i) => (i === index ? { ...question, text } : question)));
  }

  function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= questions.length) return;
    const next = [...questions];
    const [moved] = next.splice(index, 1);
    next.splice(target, 0, moved);
    onChange(next);
  }

  function remove(index: number) {
    onChange(questions.filter((_, i) => i !== index));
  }

  function add() {
    onChange([
      ...questions,
      {
        id: `question_${questions.length + 1}`,
        text: "",
        answer_type: "free_text",
        options: null,
        why_it_matters: "",
      },
    ]);
  }

  return (
    <div className="flex flex-col gap-2">
      {questions.map((question, index) => (
        <div key={question.id} className="flex items-start gap-2 rounded-md border border-border p-2">
          <div className="flex flex-col gap-0.5 pt-1">
            <button
              type="button"
              onClick={() => move(index, -1)}
              disabled={index === 0}
              aria-label="Move up"
              className="text-muted-foreground hover:text-foreground disabled:opacity-30"
            >
              <ChevronUpIcon className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={() => move(index, 1)}
              disabled={index === questions.length - 1}
              aria-label="Move down"
              className="text-muted-foreground hover:text-foreground disabled:opacity-30"
            >
              <ChevronDownIcon className="size-3.5" />
            </button>
          </div>

          <div className="flex flex-1 flex-col gap-1">
            <Input
              value={question.text}
              onChange={(event) => update(index, event.target.value)}
              placeholder="Question text"
              className="h-7 text-xs"
            />
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <span className="font-mono">{question.id}</span>
              <span>·</span>
              <span>{question.answer_type}</span>
              {question.options ? <span>· {question.options.join(", ")}</span> : null}
            </div>
          </div>

          <button
            type="button"
            onClick={() => remove(index)}
            aria-label="Remove question"
            className="mt-1 text-muted-foreground hover:text-foreground"
          >
            <XIcon className="size-3.5" />
          </button>
        </div>
      ))}

      <Button type="button" variant="outline" size="sm" onClick={add} className="self-start">
        <PlusIcon className="size-3.5" />
        Add question
      </Button>
    </div>
  );
}
