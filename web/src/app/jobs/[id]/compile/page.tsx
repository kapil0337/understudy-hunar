"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { LanguageTag } from "@/components/primitives/LanguageTag";
import { ChipList } from "@/components/compile/ChipList";
import { FactsList } from "@/components/compile/FactsList";
import { QuestionsEditor } from "@/components/compile/QuestionsEditor";
import { useJob, useUpdateRequirements } from "@/lib/hooks/useJobs";
import { useJobVersions, usePublishVersion } from "@/lib/hooks/useVersions";
import { compiledJdSchema, type CompiledJD } from "@/lib/api/compiledJd";
import { buildAgentPrompt, buildResultSchema } from "@/lib/agentPreview";
import type { components } from "@/lib/api/types";

type Language = components["schemas"]["Language"];

export default function CompilePage() {
  const { id: jobId } = useParams<{ id: string }>();
  const jobQuery = useJob(jobId);
  const updateRequirements = useUpdateRequirements(jobId);
  const versionsQuery = useJobVersions(jobId);
  const publishVersion = usePublishVersion(jobId);

  const [rawJdDraft, setRawJdDraft] = useState("");
  const [compiledDraft, setCompiledDraft] = useState<CompiledJD | null>(null);
  const [previewLanguage, setPreviewLanguage] = useState<Language | undefined>(undefined);

  const job = jobQuery.data;

  useEffect(() => {
    if (job) setRawJdDraft(job.raw_jd);
  }, [job]);

  // Reset the local editable draft whenever the server's compiled JD changes underneath it (a
  // fresh compile) — local chip/question edits are a preview only (see the note below the
  // preview), never persisted, so there is nothing to preserve across a real recompile.
  useEffect(() => {
    if (!job || job.compiled === null) {
      setCompiledDraft(null);
      return;
    }
    const result = compiledJdSchema.safeParse(job.compiled);
    setCompiledDraft(result.success ? result.data : null);
  }, [job]);

  useEffect(() => {
    if (!compiledDraft || compiledDraft.candidate_languages.length === 0) return;
    if (previewLanguage && compiledDraft.candidate_languages.includes(previewLanguage)) return;
    setPreviewLanguage(compiledDraft.candidate_languages[0]);
  }, [compiledDraft, previewLanguage]);

  const preview = useMemo(() => {
    if (!compiledDraft || !previewLanguage) return null;
    return {
      agentPrompt: buildAgentPrompt(compiledDraft, previewLanguage),
      resultSchema: buildResultSchema(compiledDraft),
    };
  }, [compiledDraft, previewLanguage]);

  if (jobQuery.isPending) {
    return (
      <div className="p-6">
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (jobQuery.isError) {
    return (
      <div className="p-6">
        <ErrorState error={jobQuery.error} onRetry={() => jobQuery.refetch()} />
      </div>
    );
  }
  if (!job) return null;

  return (
    <div className="grid h-full grid-cols-2 divide-x divide-border">
      <div className="flex flex-col gap-3 overflow-y-auto p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-muted-foreground">Raw job description</h2>
          <Button
            size="sm"
            disabled={updateRequirements.isPending || rawJdDraft.trim() === ""}
            onClick={() => updateRequirements.mutate({ raw_jd: rawJdDraft })}
          >
            {updateRequirements.isPending ? "Compiling…" : job.compiled ? "Recompile" : "Compile"}
          </Button>
        </div>
        <Textarea
          value={rawJdDraft}
          onChange={(event) => setRawJdDraft(event.target.value)}
          className="min-h-[55vh] flex-1 font-mono text-xs"
        />
        {updateRequirements.isError ? <ErrorState error={updateRequirements.error} /> : null}

        <div className="mt-4 flex flex-col gap-2">
          <h2 className="text-sm font-medium text-muted-foreground">Versions</h2>
          {versionsQuery.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : versionsQuery.isError ? (
            <ErrorState error={versionsQuery.error} onRetry={() => versionsQuery.refetch()} />
          ) : versionsQuery.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No versions yet — compile above to create one per implied language.
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {versionsQuery.data.map((version) => (
                <li
                  key={version.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">v{version.version_no}</span>
                    <LanguageTag language={version.language} />
                    <span className="text-xs text-muted-foreground">
                      {version.origin === "PATCHED" ? "patched" : "compiled"}
                    </span>
                  </div>
                  {version.hunar_agent_id ? (
                    <span className="font-mono text-xs text-status-completed">
                      {version.hunar_agent_id}
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={publishVersion.isPending}
                      onClick={() =>
                        publishVersion.mutate({
                          versionNo: version.version_no,
                          language: version.language,
                        })
                      }
                    >
                      {publishVersion.isPending ? "Publishing…" : "Publish"}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {publishVersion.isError ? <ErrorState error={publishVersion.error} /> : null}
        </div>
      </div>

      <div className="flex flex-col gap-5 overflow-y-auto p-6">
        {!compiledDraft ? (
          <EmptyState
            title="Not compiled yet"
            description="Compile the raw JD on the left to see structured requirements here."
          />
        ) : (
          <>
            <div>
              <h2 className="mb-1 text-sm font-medium text-muted-foreground">Role</h2>
              <p className="text-sm">
                {compiledDraft.role_title} · {compiledDraft.seniority} ·{" "}
                {compiledDraft.employment_type}
              </p>
            </div>

            <ChipList
              label="Must-have skills"
              values={compiledDraft.must_have_skills}
              onChange={(values) => setCompiledDraft({ ...compiledDraft, must_have_skills: values })}
            />
            <ChipList
              label="Nice-to-have skills"
              values={compiledDraft.nice_to_have_skills}
              onChange={(values) =>
                setCompiledDraft({ ...compiledDraft, nice_to_have_skills: values })
              }
            />
            <ChipList
              label="Locations"
              values={compiledDraft.locations}
              onChange={(values) => setCompiledDraft({ ...compiledDraft, locations: values })}
            />

            <div>
              <span className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Candidate languages
              </span>
              <div className="flex flex-wrap gap-1.5">
                {compiledDraft.candidate_languages.map((language) => (
                  <LanguageTag key={language} language={language} />
                ))}
              </div>
            </div>

            <div>
              <h2 className="mb-1.5 text-sm font-medium text-muted-foreground">
                Screening questions
              </h2>
              <QuestionsEditor
                questions={compiledDraft.screening_questions}
                onChange={(questions) =>
                  setCompiledDraft({ ...compiledDraft, screening_questions: questions })
                }
              />
            </div>

            <div>
              <h2 className="mb-1.5 text-sm font-medium text-muted-foreground">
                Facts the agent may state
              </h2>
              <FactsList
                values={compiledDraft.facts_the_agent_may_state}
                onChange={(values) =>
                  setCompiledDraft({ ...compiledDraft, facts_the_agent_may_state: values })
                }
              />
            </div>

            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <h2 className="text-sm font-medium text-muted-foreground">Live preview</h2>
                {compiledDraft.candidate_languages.length > 1 ? (
                  <Select
                    value={previewLanguage}
                    onValueChange={(value) =>
                      setPreviewLanguage((value ?? undefined) as Language | undefined)
                    }
                  >
                    <SelectTrigger size="sm" className="w-36">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {compiledDraft.candidate_languages.map((language) => (
                        <SelectItem key={language} value={language}>
                          {language}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : null}
              </div>

              {preview ? (
                <div className="flex flex-col gap-3">
                  <div>
                    <p className="mb-1 text-xs text-muted-foreground">agent_prompt</p>
                    <pre className="max-h-64 overflow-y-auto rounded-lg border border-border bg-card p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                      {preview.agentPrompt}
                    </pre>
                  </div>
                  <div>
                    <p className="mb-1 text-xs text-muted-foreground">result_schema</p>
                    <pre className="max-h-64 overflow-y-auto rounded-lg border border-border bg-card p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                      {JSON.stringify(preview.resultSchema, null, 2)}
                    </pre>
                  </div>
                </div>
              ) : null}

              <p className="mt-2 text-xs text-muted-foreground">
                Preview only — edits above aren&apos;t saved. Recompile the raw JD (left) to
                persist a change, or Publish an existing version below to send its actual built
                prompt to Hunar.
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
