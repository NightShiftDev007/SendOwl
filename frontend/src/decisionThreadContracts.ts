import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const endpoint = "/api/v2/decision-threads";
const uuidSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const singleLineSchema = z.string().trim().min(1).max(300).regex(/^[^\r\n]+$/u);

export const decisionThreadContextRequestSchema = z.object({
  world_model_id: uuidSchema,
  world_snapshot_id: uuidSchema,
  scenario_id: uuidSchema.nullable(),
  cohort_id: uuidSchema.nullable(),
  semantic_experiment_id: uuidSchema.nullable(),
}).strict().superRefine((value, context) => {
  if (value.semantic_experiment_id !== null && (value.scenario_id === null || value.cohort_id === null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Experiment requires Scenario and Cohort" });
  }
});

export const decisionThreadCreateRequestSchema = z.object({
  world_model_id: uuidSchema,
  world_snapshot_id: uuidSchema,
  scenario_id: uuidSchema.nullable(),
  cohort_id: uuidSchema.nullable(),
  semantic_experiment_id: uuidSchema.nullable(),
  title: singleLineSchema,
  decision_question: z.string().trim().min(1).max(2_000),
}).strict().superRefine((value, context) => {
  if (value.semantic_experiment_id !== null && (value.scenario_id === null || value.cohort_id === null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Experiment requires Scenario and Cohort" });
  }
});

export const decisionThreadRevisionSchema = z.object({
  id: uuidSchema,
  version: z.number().int().positive(),
  world_model_id: uuidSchema,
  world_snapshot_id: uuidSchema,
  snapshot_sha256: sha256DigestSchema,
  scenario_id: uuidSchema.nullable(),
  scenario_sha256: sha256DigestSchema.nullable(),
  cohort_id: uuidSchema.nullable(),
  cohort_sha256: sha256DigestSchema.nullable(),
  semantic_experiment_id: uuidSchema.nullable(),
  experiment_sha256: sha256DigestSchema.nullable(),
  created_at: timestampSchema,
}).strict().superRefine((value, context) => {
  const pairs = [
    [value.scenario_id, value.scenario_sha256],
    [value.cohort_id, value.cohort_sha256],
    [value.semantic_experiment_id, value.experiment_sha256],
  ];
  if (pairs.some(([identity, digest]) => (identity === null) !== (digest === null))) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Context identities and digests must be paired" });
  }
});

export const decisionThreadSummarySchema = z.object({
  id: uuidSchema,
  title: singleLineSchema,
  decision_question: z.string().trim().min(1).max(2_000),
  created_at: timestampSchema,
  latest_revision: decisionThreadRevisionSchema,
}).strict();

export const decisionThreadDetailSchema = decisionThreadSummarySchema.extend({
  revisions: z.array(decisionThreadRevisionSchema).min(1),
}).strict().superRefine((value, context) => {
  if (value.revisions.some((revision, index) => revision.version !== index + 1)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Revision versions must be contiguous" });
  }
  if (value.revisions.at(-1)?.id !== value.latest_revision.id) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Latest revision must close history" });
  }
});

export const decisionThreadsResponseSchema = z.object({
  items: z.array(decisionThreadSummarySchema),
  total: z.number().int().nonnegative(),
}).strict();

export type DecisionThreadContextRequest = z.infer<typeof decisionThreadContextRequestSchema>;
export type DecisionThreadCreateRequest = z.infer<typeof decisionThreadCreateRequestSchema>;
export type DecisionThreadDetail = z.infer<typeof decisionThreadDetailSchema>;
export type DecisionThreadsResponse = z.infer<typeof decisionThreadsResponseSchema>;

export function fetchDecisionThreads(signal: AbortSignal): Promise<DecisionThreadsResponse> {
  return getJson(endpoint, decisionThreadsResponseSchema, signal);
}

export function fetchDecisionThread(id: string, signal: AbortSignal): Promise<DecisionThreadDetail> {
  return getJson(`${endpoint}/${encodeURIComponent(id)}`, decisionThreadDetailSchema, signal);
}

export function createDecisionThread(request: DecisionThreadCreateRequest, signal: AbortSignal): Promise<DecisionThreadDetail> {
  return postJson(endpoint, decisionThreadCreateRequestSchema.parse(request), decisionThreadDetailSchema, signal);
}

export function appendDecisionThreadRevision(id: string, request: DecisionThreadContextRequest, signal: AbortSignal): Promise<DecisionThreadDetail> {
  return postJson(`${endpoint}/${encodeURIComponent(id)}/revisions`, decisionThreadContextRequestSchema.parse(request), decisionThreadDetailSchema, signal);
}
