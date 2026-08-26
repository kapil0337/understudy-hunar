/**
 * `RunRead.scores` and `CaseRead.metrics`/`failures` are opaque JSON at the OpenAPI level —
 * they're `RehearsalScore.model_dump()` (backend/app/schemas/rehearsal.py) stored straight into a
 * JSONB column, never modelled as their own response schema. Parsed defensively here, mirroring
 * that Pydantic shape exactly, the same pattern as lib/api/compiledJd.ts.
 */
import { z } from "zod";

export const transcriptTurnSchema = z.object({
  speaker: z.enum(["agent", "candidate"]),
  text: z.string(),
  turn: z.number(),
});
export type TranscriptTurn = z.infer<typeof transcriptTurnSchema>;

export const metricSchema = z.enum([
  "extraction_accuracy",
  "coverage",
  "faithfulness",
  "efficiency",
]);
export type Metric = z.infer<typeof metricSchema>;

export const severitySchema = z.enum(["critical", "major", "minor"]);
export type Severity = z.infer<typeof severitySchema>;

export const failureSchema = z.object({
  persona_id: z.uuid(),
  metric: metricSchema,
  severity: severitySchema,
  description: z.string(),
  transcript_excerpt: z.string(),
});
export type Failure = z.infer<typeof failureSchema>;

const fieldAccuracySchema = z.object({
  persona_id: z.uuid(),
  field: z.string(),
  expected: z.unknown(),
  actual: z.unknown(),
  correct: z.boolean(),
});
export type FieldAccuracy = z.infer<typeof fieldAccuracySchema>;

const extractionAccuracyResultSchema = z.object({
  score: z.number(),
  fields: z.array(fieldAccuracySchema),
});

const efficiencyCaseSchema = z.object({
  persona_id: z.uuid(),
  estimated_seconds: z.number(),
  turn_count: z.number(),
  score: z.number(),
  flagged: z.boolean(),
});

const efficiencyResultSchema = z.object({
  score: z.number(),
  cases: z.array(efficiencyCaseSchema),
});

const coverageCaseSchema = z.object({
  persona_id: z.uuid(),
  asked: z.record(z.string(), z.boolean()),
});

const coverageResultSchema = z.object({
  score: z.number(),
  cases: z.array(coverageCaseSchema),
});

const faithfulnessViolationSchema = z.object({
  quote: z.string(),
  reason: z.string(),
});

const faithfulnessCaseSchema = z.object({
  persona_id: z.uuid(),
  score: z.number(),
  violations: z.array(faithfulnessViolationSchema),
});

const faithfulnessResultSchema = z.object({
  score: z.number(),
  cases: z.array(faithfulnessCaseSchema),
});

/** RunRead.scores, parsed. The four components plus the composite they're weighted into — see
 * backend/app/services/rehearsal/score.py's _WEIGHTS (40/25/25/10). */
export const rehearsalScoreSchema = z.object({
  composite: z.number(),
  extraction_accuracy: extractionAccuracyResultSchema,
  coverage: coverageResultSchema,
  faithfulness: faithfulnessResultSchema,
  efficiency: efficiencyResultSchema,
  failures: z.array(failureSchema),
});
export type RehearsalScore = z.infer<typeof rehearsalScoreSchema>;

export const METRIC_WEIGHT: Record<Metric, number> = {
  extraction_accuracy: 40,
  coverage: 25,
  faithfulness: 25,
  efficiency: 10,
};

export const METRIC_ORDER: Metric[] = ["extraction_accuracy", "coverage", "faithfulness", "efficiency"];

export const METRIC_LABEL: Record<Metric, string> = {
  extraction_accuracy: "Extraction accuracy",
  coverage: "Coverage",
  faithfulness: "Faithfulness",
  efficiency: "Efficiency",
};

/** child minus parent, per metric plus composite — mirrors
 * backend/app/services/rehearsal/patch.py's score_delta exactly. Computed client-side because
 * POST /patches/{id}/accept no longer returns it directly: the new run isn't scored yet at
 * accept time (rehearsing it is deferred to app/worker.py), so the caller polls it to COMPLETED
 * first and calls this once both scores are in hand. */
export function computeScoreDelta(parent: RehearsalScore, child: RehearsalScore): Record<string, number> {
  const delta: Record<string, number> = { composite: child.composite - parent.composite };
  for (const metric of METRIC_ORDER) {
    delta[metric] = child[metric].score - parent[metric].score;
  }
  return delta;
}

/** CaseRead.metrics, parsed — the same four components, but narrowed to one persona (built by
 * backend/app/services/rehearsal/run.py's _apply_case_scores). Each component is null only if
 * that case failed before scoring ran. */
export const caseMetricsSchema = z.object({
  extraction_accuracy: z.object({ fields: z.array(fieldAccuracySchema) }),
  efficiency: efficiencyCaseSchema.nullable(),
  coverage: coverageCaseSchema.nullable(),
  faithfulness: faithfulnessCaseSchema.nullable(),
});
export type CaseMetrics = z.infer<typeof caseMetricsSchema>;

/** CaseRead.failures, parsed — this persona's slice of the run-wide failures list. */
export const caseFailuresSchema = z.array(failureSchema);

/** PatchRead.rationale, parsed — backend/app/services/rehearsal/patch.py's _PatchRationaleItem.
 * failure_id is the 1-based index into the top-6 failures list the patcher was shown (see
 * TOP_FAILURES in that module), as a string — not a database id. */
export const patchRationaleItemSchema = z.object({
  failure_id: z.string(),
  change_summary: z.string(),
  quoted_new_text: z.string(),
});
export type PatchRationaleItem = z.infer<typeof patchRationaleItemSchema>;
export const patchRationaleSchema = z.array(patchRationaleItemSchema);
