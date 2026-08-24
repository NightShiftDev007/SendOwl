import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const identifierSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });

export const researchInterviewCitationSchema = z.object({
  position: z.number().int().min(0).max(19),
  source_kind: z.literal("research_run"),
  target_id: identifierSchema,
  source_label: z.string().trim().min(1).max(500),
  quote: z.string().min(1).max(500),
  start_offset: z.number().int().min(0),
  end_offset: z.number().int().min(1),
}).strict().refine(
  (item) => item.end_offset - item.start_offset === item.quote.length,
  { message: "Research interview citation offsets must span the quote" },
);

const researchInterviewPersonaSchema = z.object({
  id: identifierSchema,
  position: z.number().int().min(0).max(7),
  persona_id: z.string().min(1).max(128),
  display_name: z.string().trim().min(1).max(200),
  profile_sha256: sha256DigestSchema,
}).strict();

export const researchPersonaInterviewSchema = z.object({
  id: identifierSchema,
  research_project_id: identifierSchema,
  research_simulation_run_id: identifierSchema,
  run_spec_sha256: sha256DigestSchema,
  graph_memory_sha256: sha256DigestSchema,
  cohort_id: identifierSchema,
  cohort_sha256: sha256DigestSchema,
  persona: researchInterviewPersonaSchema,
  question: z.string().trim().min(2).max(1000),
  source_sha256: sha256DigestSchema,
  interview_sha256: sha256DigestSchema,
  model_name: z.string().trim().min(1).max(200),
  semantic_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("sandowl-run-persona-interview/v1"),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  answer_markdown: z.string().min(1).max(2000).nullable(),
  citations: z.array(researchInterviewCitationSchema).max(20),
  answer_sha256: sha256DigestSchema.nullable(),
  error_code: z.string().min(1).max(128).nullable(),
  error_message: z.string().min(1).max(500).nullable(),
}).strict().superRefine((item, context) => {
  const terminal = item.status === "succeeded" || item.status === "failed";
  const timestampsValid = item.status === "queued"
    ? item.started_at === null && item.completed_at === null
    : item.started_at !== null && (terminal ? item.completed_at !== null : item.completed_at === null);
  const outputValid = item.status === "succeeded"
    ? item.answer_markdown !== null && item.citations.length > 0 && item.answer_sha256 !== null
      && item.error_code === null && item.error_message === null
    : item.answer_markdown === null && item.citations.length === 0 && item.answer_sha256 === null
      && (item.status === "failed"
        ? item.error_code !== null && item.error_message !== null
        : item.error_code === null && item.error_message === null);
  if (!timestampsValid || !outputValid) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Research interview lifecycle is invalid" });
  }
  if (!item.citations.every((citation, position) => citation.position === position)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Research interview citations are not contiguous" });
  }
});

export const researchPersonaInterviewsResponseSchema = z.object({
  items: z.array(researchPersonaInterviewSchema),
  total: z.number().int().min(0),
}).strict().refine((response) => response.total === response.items.length, {
  message: "Research interview total must match items",
});

export const researchPersonaInterviewSessionSchema = z.object({
  id: identifierSchema,
  research_project_id: identifierSchema,
  research_simulation_run_id: identifierSchema,
  run_spec_sha256: sha256DigestSchema,
  graph_memory_sha256: sha256DigestSchema,
  cohort_id: identifierSchema,
  cohort_sha256: sha256DigestSchema,
  question: z.string().trim().min(2).max(1000),
  persona_count: z.number().int().min(2).max(8),
  session_sha256: sha256DigestSchema,
  model_name: z.string().trim().min(1).max(200),
  semantic_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("sandowl-run-persona-interview-session/v1"),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  created_at: timestampSchema,
  interviews: z.array(researchPersonaInterviewSchema).min(2).max(8),
}).strict();

export type ResearchPersonaInterview = z.infer<typeof researchPersonaInterviewSchema>;
export type ResearchPersonaInterviewsResponse = z.infer<typeof researchPersonaInterviewsResponseSchema>;
export type ResearchPersonaInterviewSession = z.infer<typeof researchPersonaInterviewSessionSchema>;

function runPath(projectId: string, runId: string): string {
  return `/api/v2/research-projects/${encodeURIComponent(identifierSchema.parse(projectId))}/runs/${encodeURIComponent(identifierSchema.parse(runId))}`;
}

export function fetchResearchPersonaInterviews(
  projectId: string,
  runId: string,
  signal: AbortSignal,
): Promise<ResearchPersonaInterviewsResponse> {
  return getJson(
    `${runPath(projectId, runId)}/persona-interviews`,
    researchPersonaInterviewsResponseSchema,
    signal,
  );
}

export function createResearchPersonaInterview(
  projectId: string,
  runId: string,
  personaId: string,
  question: string,
  signal: AbortSignal,
): Promise<ResearchPersonaInterview> {
  return postJson(
    `${runPath(projectId, runId)}/persona-interviews`,
    { persona_id: identifierSchema.parse(personaId), question },
    researchPersonaInterviewSchema,
    signal,
  );
}

export function createResearchPersonaInterviewSession(
  projectId: string,
  runId: string,
  personaIds: readonly string[],
  question: string,
  signal: AbortSignal,
): Promise<ResearchPersonaInterviewSession> {
  return postJson(
    `${runPath(projectId, runId)}/persona-interview-sessions`,
    { persona_ids: personaIds.map((item) => identifierSchema.parse(item)), question },
    researchPersonaInterviewSessionSchema,
    signal,
  );
}
