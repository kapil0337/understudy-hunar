/**
 * Client-side port of backend/app/services/jd_compiler.py's build_agent_prompt /
 * build_introduction / build_result_prompt / build_result_schema — all four are pure string/dict
 * templating with no I/O, which is what makes porting them safe. This is what lets the compile
 * screen regenerate a live preview on every edit with no round trip.
 *
 * This is NOT what gets published. There is no endpoint that accepts an edited CompiledJD — the
 * only way to persist a change is PUT /jobs/{id}/requirements (recompiling the raw JD) or
 * accepting a rehearsal patch. Publish always sends whatever agent_prompt/result_schema the
 * backend itself built for the version being published, not this preview. Keep this in sync by
 * hand if jd_compiler.py's templates change — there is no generated contract to catch drift here.
 */
import type { CompiledJD } from "@/lib/api/compiledJd";
import type { components } from "@/lib/api/types";

type Language = components["schemas"]["Language"];

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

export function buildAgentPrompt(compiled: CompiledJD, language: Language): string {
  const questions = compiled.screening_questions
    .map((question, index) => {
      const options =
        question.answer_type === "enum" && question.options && question.options.length > 0
          ? `\n   Offer these options: ${question.options.join(", ")}`
          : "";
      return `${index + 1}. (${question.answer_type}) ${question.text}${options}`;
    })
    .join("\n");
  const facts = compiled.facts_the_agent_may_state.map((fact) => `- ${fact}`).join("\n");

  return `You are {persona_name}, a recruiter calling {callee_name} about a {role_title} role in {role_location}. Speak ${titleCase(language)}.

GOAL
Screen this candidate in under 90 seconds. Be warm, direct, and quick. This is a phone call:
short sentences, one question at a time, no lists read aloud.

WHAT YOU MAY SAY ABOUT THE ROLE
You may state ONLY the following facts. This list is exhaustive.
${facts}

If asked anything not covered above — exact pay for their case, contract terms, start date
guarantees, anything at all — say you do not have that detail and a human recruiter will
follow up. NEVER guess, estimate, extrapolate, or invent a fact about this role. Saying "I
don't have that detail" is always the correct answer when the fact is not on the list above.

SCREENING QUESTIONS — ask these in order, all of them:
${questions}

Ask them conversationally, not as a form. Accept short answers and move on. Do not ask for
documents, numbers they would need to look up, or anything they could not answer from memory.

IF THEY ARE NOT INTERESTED
Thank them sincerely, do not push or re-pitch more than once, confirm they want no further
contact if they say so, and end the call politely.

CLOSING
Summarise the next step in one sentence, thank them, and end. Target under 90 seconds total.
`;
}

export function buildIntroduction(compiled: CompiledJD): string {
  const location = compiled.locations.length > 0 ? ` in ${compiled.locations[0]}` : "";
  return (
    `Hi {callee_name}, this is {persona_name} calling about a ${compiled.role_title} opening` +
    `${location}. Do you have ninety seconds to talk?`
  );
}

export function buildResultPrompt(compiled: CompiledJD): string {
  const ids = compiled.screening_questions.map((question) => question.id).join(", ");
  return `From this call, extract exactly these fields: ${ids}, interested, qualified, earliest_start,
rejection_reason.

Use only what the candidate actually said. If a question was not asked or not answered, leave
that field empty rather than guessing. Set qualified to false if any knockout criterion was
failed. Set rejection_reason only when interested or qualified is false.
`;
}

interface ResultSchemaProperty {
  type: "boolean" | "number" | "string";
  description: string;
  enum?: string[];
}

export interface ResultSchema {
  type: "object";
  properties: Record<string, ResultSchemaProperty>;
  required: string[];
}

export function buildResultSchema(compiled: CompiledJD): ResultSchema {
  const properties: Record<string, ResultSchemaProperty> = {};

  for (const question of compiled.screening_questions) {
    if (question.answer_type === "boolean") {
      properties[question.id] = { type: "boolean", description: question.text };
    } else if (question.answer_type === "number") {
      properties[question.id] = { type: "number", description: question.text };
    } else if (question.answer_type === "enum") {
      properties[question.id] = {
        type: "string",
        enum: question.options ?? [],
        description: question.text,
      };
    } else {
      properties[question.id] = { type: "string", description: question.text };
    }
  }

  properties.interested = {
    type: "boolean",
    description: "Did the candidate express interest in proceeding?",
  };
  properties.qualified = {
    type: "boolean",
    description: "Did the candidate pass every knockout criterion?",
  };
  properties.earliest_start = {
    type: "string",
    description: "When the candidate said they could start, in their own words.",
  };
  properties.rejection_reason = {
    type: "string",
    description: "If not qualified or not interested, the reason. Empty otherwise.",
  };

  return { type: "object", properties, required: Object.keys(properties) };
}
