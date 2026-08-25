/**
 * `CandidateRead.match_breakdown` is opaque JSON at the OpenAPI level — it's
 * `MatchBreakdown.model_dump()` (backend/app/schemas/ranking.py), never its own response schema.
 * Parsed defensively here, same pattern as compiledJd.ts and rehearsalScore.ts.
 */
import { z } from "zod";

const matchComponentSchema = z.object({
  score: z.number(),
  weight: z.number(),
});

export const matchBreakdownSchema = z.object({
  match_score: z.number(),
  components: z.record(z.string(), matchComponentSchema),
});
export type MatchBreakdown = z.infer<typeof matchBreakdownSchema>;

/** backend/app/services/ranking.py's _WEIGHTS — component order for a consistent ScoreBar. */
export const MATCH_COMPONENT_ORDER = [
  "skill_overlap",
  "title_similarity",
  "location_match",
  "experience_fit",
] as const;

export const MATCH_COMPONENT_LABEL: Record<string, string> = {
  skill_overlap: "Skill overlap",
  title_similarity: "Title similarity",
  location_match: "Location match",
  experience_fit: "Experience fit",
};
