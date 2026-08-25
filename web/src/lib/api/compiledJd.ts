/**
 * `JobRead.compiled` is `dict[str, Any] | null` at the OpenAPI level — the backend's CompiledJD
 * Pydantic model never crosses the wire as its own typed response, so (like RunRead.scores and
 * CaseRead.metrics) it needs its own defensive parser here rather than a generated type. Shape
 * mirrors backend/app/schemas/compiled_jd.py exactly.
 */
import { z } from "zod";
import { languageSchema } from "./schemas";

export const answerTypeSchema = z.enum(["boolean", "number", "enum", "free_text"]);
export type AnswerType = z.infer<typeof answerTypeSchema>;

export const knockoutOperatorSchema = z.enum([
  "eq",
  "neq",
  "gte",
  "lte",
  "gt",
  "lt",
  "in",
  "not_in",
]);

export const screeningQuestionSchema = z.object({
  id: z.string(),
  text: z.string(),
  answer_type: answerTypeSchema,
  options: z.array(z.string()).nullable(),
  why_it_matters: z.string(),
});
export type ScreeningQuestion = z.infer<typeof screeningQuestionSchema>;

export const knockoutCriterionSchema = z.object({
  question_id: z.string(),
  operator: knockoutOperatorSchema,
  value: z.union([z.boolean(), z.number(), z.string(), z.array(z.string())]),
});
export type KnockoutCriterion = z.infer<typeof knockoutCriterionSchema>;

export const searchQuerySchema = z.object({
  titles: z.array(z.string()),
  skills: z.array(z.string()),
  locations: z.array(z.string()),
  min_years: z.number().nullable(),
});

export const compiledJdSchema = z.object({
  role_title: z.string(),
  seniority: z.string(),
  employment_type: z.string(),
  must_have_skills: z.array(z.string()),
  nice_to_have_skills: z.array(z.string()),
  min_years_experience: z.number().nullable(),
  locations: z.array(z.string()),
  shift_pattern: z.string().nullable(),
  salary_range: z.string().nullable(),
  candidate_languages: z.array(languageSchema),
  screening_questions: z.array(screeningQuestionSchema),
  knockout_criteria: z.array(knockoutCriterionSchema),
  facts_the_agent_may_state: z.array(z.string()),
  search_query: searchQuerySchema,
});
export type CompiledJD = z.infer<typeof compiledJdSchema>;
