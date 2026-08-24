import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import {
  evidenceBundleContentSchema,
  evidenceBundleDetailSchema,
  evidenceBundlePolicyContentSchema,
} from "./evidenceBundleContracts";
import { sha256DigestSchema } from "./mediaContracts";

const endpoint = "/api/v2/report-agent";
const identifierSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });

export const reportAgentPlanSectionSchema = z
  .object({
    position: z.number().int().min(0).max(5),
    title: z.string().trim().min(1).max(200).regex(/^[^\r\n]+$/u),
    focus: z.string().trim().min(2).max(500),
  })
  .strict();

export const reportAgentRunRequestSchema = z
  .object({
    world_model_id: identifierSchema,
    world_snapshot_id: identifierSchema,
    snapshot_sha256: sha256DigestSchema,
    objective: z.string().trim().min(2).max(1000),
    outline: z.array(reportAgentPlanSectionSchema).min(2).max(6),
    max_tool_calls: z.number().int().min(1).max(20),
  })
  .strict()
  .refine(
    (request) => request.outline.every((section, position) => section.position === position),
    { message: "ReportAgent outline positions must be contiguous", path: ["outline"] },
  );

export const reportAgentToolCallSchema = z
  .object({
    id: identifierSchema,
    run_id: identifierSchema,
    position: z.number().int().min(0).max(19),
    tool_name: z.enum([
      "list_evidence", "read_media", "read_policy", "read_simulation_run",
      "read_world_snapshot", "read_world_graph", "read_persona_interviews",
    ]),
    target_id: identifierSchema.nullable(),
    input_sha256: sha256DigestSchema,
    result_sha256: sha256DigestSchema,
    call_sha256: sha256DigestSchema,
    created_at: timestampSchema,
  })
  .strict()
  .refine(
    (call) => (call.tool_name === "list_evidence") === (call.target_id === null),
    { message: "ReportAgent tool target must match its tool", path: ["target_id"] },
  );

export const reportAgentRunSchema = z
  .object({
    id: identifierSchema,
    world_model_id: identifierSchema,
    world_snapshot_id: identifierSchema,
    snapshot_sha256: sha256DigestSchema,
    objective: z.string().trim().min(2).max(1000),
    outline: z.array(reportAgentPlanSectionSchema).min(2).max(6),
    max_tool_calls: z.number().int().min(1).max(20),
    schema_version: z.enum([
      "bounded-report-agent-evidence/v1",
      "sandowl-research-run-report-agent/v1",
      "sandowl-research-run-report-agent/v2",
    ]),
    research_simulation_run_id: identifierSchema.nullable(),
    research_run_report_sha256: sha256DigestSchema.nullable(),
    run_sha256: sha256DigestSchema,
    created_at: timestampSchema,
    tool_calls: z.array(reportAgentToolCallSchema).max(20),
    tool_call_count: z.number().int().min(0).max(20),
    remaining_tool_calls: z.number().int().min(0).max(20),
  })
  .strict()
  .superRefine((run, context) => {
    if (!run.outline.every((section, position) => section.position === position)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["outline"],
        message: "ReportAgent outline positions must be contiguous",
      });
    }
    if (!run.tool_calls.every(
      (call, position) => call.position === position && call.run_id === run.id,
    )) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["tool_calls"],
        message: "ReportAgent tool calls must be contiguous and belong to the run",
      });
    }
    if (
      run.tool_call_count !== run.tool_calls.length
      || run.remaining_tool_calls !== run.max_tool_calls - run.tool_call_count
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["remaining_tool_calls"],
        message: "ReportAgent tool budget projection is inconsistent",
      });
    }
    const researchScope = run.schema_version === "sandowl-research-run-report-agent/v1"
      || run.schema_version === "sandowl-research-run-report-agent/v2";
    if (
      researchScope !== (run.research_simulation_run_id !== null)
      || researchScope !== (run.research_run_report_sha256 !== null)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["research_simulation_run_id"],
        message: "ReportAgent research-run scope does not match its schema",
      });
    }
  });

export const reportAgentEvidenceDirectoryResultSchema = z
  .object({ run: reportAgentRunSchema, bundle: evidenceBundleDetailSchema })
  .strict();

export const reportAgentMediaReadResultSchema = z
  .object({ run: reportAgentRunSchema, content: evidenceBundleContentSchema })
  .strict();

export const reportAgentPolicyReadResultSchema = z
  .object({ run: reportAgentRunSchema, content: evidenceBundlePolicyContentSchema })
  .strict();

export const reportAgentDraftCitationSchema = z
  .object({
    position: z.number().int().min(0).max(19),
    evidence_kind: z.enum([
      "media_article",
      "policy_document",
      "world_snapshot",
      "world_graph",
      "simulation_run",
      "persona_interviews",
    ]),
    target_id: identifierSchema,
    tool_call_position: z.number().int().min(0).max(19),
    source_label: z.string().trim().min(1).max(500),
    quote: z.string().min(1).max(500),
    start_offset: z.number().int().min(0),
    end_offset: z.number().int().min(1),
  })
  .strict()
  .refine((citation) => citation.end_offset - citation.start_offset === citation.quote.length, {
    message: "ReportAgent citation offsets must span the exact quote",
    path: ["end_offset"],
  });

export const reportAgentDraftSectionSchema = z
  .object({
    position: z.number().int().min(0).max(5),
    title: z.string().trim().min(1).max(200),
    body_markdown: z.string().trim().min(1).max(5000),
    citations: z.array(reportAgentDraftCitationSchema).min(1).max(20),
  })
  .strict()
  .refine(
    (section) => section.citations.every((citation, position) => citation.position === position),
    { message: "ReportAgent citation positions must be contiguous", path: ["citations"] },
  );

export const reportAgentCitedDraftSchema = z
  .object({
    id: identifierSchema,
    run_id: identifierSchema,
    run_sha256: sha256DigestSchema,
    evidence_call_count: z.number().int().min(1).max(20),
    evidence_calls_sha256: sha256DigestSchema,
    input_sha256: sha256DigestSchema,
    retry_of_draft_id: identifierSchema.nullable(),
    retry_of_input_sha256: sha256DigestSchema.nullable(),
    attempt_number: z.number().int().min(1).max(5),
    model_name: z.string().trim().min(1).max(200),
    semantic_config_sha256: sha256DigestSchema,
    prompt_schema_version: z.literal("bounded-report-agent-cited-draft/v1"),
    status: z.enum(["queued", "running", "succeeded", "failed"]),
    created_at: timestampSchema,
    started_at: timestampSchema.nullable(),
    completed_at: timestampSchema.nullable(),
    title: z.string().trim().min(1).max(200).nullable(),
    sections: z.array(reportAgentDraftSectionSchema).max(6),
    draft_sha256: sha256DigestSchema.nullable(),
    error_code: z.string().trim().min(1).max(128).nullable(),
    error_message: z.string().trim().min(1).max(500).nullable(),
  })
  .strict()
  .superRefine((draft, context) => {
    const terminal = draft.status === "succeeded" || draft.status === "failed";
    const timestampsValid = draft.status === "queued"
      ? draft.started_at === null && draft.completed_at === null
      : draft.started_at !== null && (terminal ? draft.completed_at !== null : draft.completed_at === null);
    const outputValid = draft.status === "succeeded"
      ? draft.title !== null && draft.sections.length >= 2 && draft.draft_sha256 !== null
        && draft.error_code === null && draft.error_message === null
      : draft.title === null && draft.sections.length === 0 && draft.draft_sha256 === null
        && (draft.status === "failed"
          ? draft.error_code !== null && draft.error_message !== null
          : draft.error_code === null && draft.error_message === null);
    if (!timestampsValid || !outputValid) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "ReportAgent draft fields do not match lifecycle status",
      });
    }
    if (!draft.sections.every((section, position) => section.position === position)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["sections"],
        message: "ReportAgent draft section positions must be contiguous",
      });
    }
    const hasRetryParent = draft.retry_of_draft_id !== null
      && draft.retry_of_input_sha256 !== null;
    if ((draft.attempt_number === 1) === hasRetryParent) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["attempt_number"],
        message: "ReportAgent retry lineage must match attempt number",
      });
    }
    if (draft.retry_of_input_sha256 !== null
      && draft.retry_of_input_sha256 !== draft.input_sha256) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["retry_of_input_sha256"],
        message: "ReportAgent retry must preserve the original input digest",
      });
    }
  });

export const reportAgentDraftsResponseSchema = z
  .object({
    items: z.array(reportAgentCitedDraftSchema),
    total: z.number().int().min(0),
  })
  .strict()
  .refine((response) => response.total === response.items.length, {
    message: "ReportAgent draft total must match items",
    path: ["total"],
  });

export type ReportAgentRunRequest = z.infer<typeof reportAgentRunRequestSchema>;
export type ReportAgentRun = z.infer<typeof reportAgentRunSchema>;
export type ReportAgentMediaReadResult = z.infer<typeof reportAgentMediaReadResultSchema>;
export type ReportAgentPolicyReadResult = z.infer<typeof reportAgentPolicyReadResultSchema>;
export type ReportAgentCitedDraft = z.infer<typeof reportAgentCitedDraftSchema>;

export function createReportAgentRun(
  request: ReportAgentRunRequest,
  signal: AbortSignal,
): Promise<ReportAgentRun> {
  return postJson(
    `${endpoint}/runs`,
    reportAgentRunRequestSchema.parse(request),
    reportAgentRunSchema,
    signal,
  );
}

export function createResearchRunReportAgent(
  projectId: string,
  runId: string,
  signal: AbortSignal,
): Promise<ReportAgentRun> {
  return postJson(
    `/api/v2/research-projects/${encodeURIComponent(identifierSchema.parse(projectId))}`
      + `/runs/${encodeURIComponent(identifierSchema.parse(runId))}/report-agent`,
    {},
    reportAgentRunSchema,
    signal,
  );
}

export function fetchResearchRunReportAgent(
  projectId: string,
  runId: string,
  signal: AbortSignal,
): Promise<ReportAgentRun | null> {
  return getJson(
    `/api/v2/research-projects/${encodeURIComponent(identifierSchema.parse(projectId))}`
      + `/runs/${encodeURIComponent(identifierSchema.parse(runId))}/report-agent`,
    reportAgentRunSchema.nullable(),
    signal,
  );
}

export function fetchReportAgentRun(
  runId: string,
  signal: AbortSignal,
): Promise<ReportAgentRun> {
  return getJson(
    `${endpoint}/runs/${encodeURIComponent(identifierSchema.parse(runId))}`,
    reportAgentRunSchema,
    signal,
  );
}

export function listReportAgentEvidence(
  runId: string,
  signal: AbortSignal,
): Promise<z.infer<typeof reportAgentEvidenceDirectoryResultSchema>> {
  return postJson(
    `${endpoint}/runs/${encodeURIComponent(identifierSchema.parse(runId))}/tools/list-evidence`,
    {},
    reportAgentEvidenceDirectoryResultSchema,
    signal,
  );
}

export function readReportAgentMedia(
  runId: string,
  articleId: string,
  signal: AbortSignal,
): Promise<ReportAgentMediaReadResult> {
  return postJson(
    `${endpoint}/runs/${encodeURIComponent(identifierSchema.parse(runId))}/tools/read-media/${encodeURIComponent(identifierSchema.parse(articleId))}`,
    {},
    reportAgentMediaReadResultSchema,
    signal,
  );
}

export function readReportAgentPolicy(
  runId: string,
  policyVersionId: string,
  signal: AbortSignal,
): Promise<ReportAgentPolicyReadResult> {
  return postJson(
    `${endpoint}/runs/${encodeURIComponent(identifierSchema.parse(runId))}/tools/read-policy/${encodeURIComponent(identifierSchema.parse(policyVersionId))}`,
    {},
    reportAgentPolicyReadResultSchema,
    signal,
  );
}

export function enqueueReportAgentDraft(
  runId: string,
  signal: AbortSignal,
): Promise<ReportAgentCitedDraft> {
  return postJson(
    `${endpoint}/runs/${encodeURIComponent(identifierSchema.parse(runId))}/drafts`,
    {},
    reportAgentCitedDraftSchema,
    signal,
  );
}

export function fetchReportAgentDraft(
  draftId: string,
  signal: AbortSignal,
): Promise<ReportAgentCitedDraft> {
  return getJson(
    `${endpoint}/drafts/${encodeURIComponent(identifierSchema.parse(draftId))}`,
    reportAgentCitedDraftSchema,
    signal,
  );
}

export function retryReportAgentDraft(
  draftId: string,
  signal: AbortSignal,
): Promise<ReportAgentCitedDraft> {
  return postJson(
    `${endpoint}/drafts/${encodeURIComponent(identifierSchema.parse(draftId))}/retry`,
    {},
    reportAgentCitedDraftSchema,
    signal,
  );
}

export function listReportAgentDrafts(
  runId: string,
  signal: AbortSignal,
): Promise<z.infer<typeof reportAgentDraftsResponseSchema>> {
  return getJson(
    `${endpoint}/runs/${encodeURIComponent(identifierSchema.parse(runId))}/drafts`,
    reportAgentDraftsResponseSchema,
    signal,
  );
}
