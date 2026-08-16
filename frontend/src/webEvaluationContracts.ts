import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";
import { parentProgressSchema, type ParentProgress } from "./parentProgress";

const uuidSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const textSchema = z.string().trim().min(1);
const statusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const taskIdSchema = z.literal("matraix/quotes-playwright-choice");

export const webTaskSchema = z.object({
  task_id: taskIdSchema,
  version: z.literal("1.0.0"),
  schema_version: z.literal("matraix-web-task/quote-choice-v1"),
  title: z.literal("Quote to save"),
  domain: z.literal("arts-culture"),
  source: z.object({
    kind: z.literal("source_sample"),
    project: z.literal("MatrAIx"),
    canonical_path: z.literal("application/tasks/example-web-playwright_quote-choice"),
    production_sut: z.literal(false),
  }).strict(),
  transport: z.literal("playwright_chromium"),
  target_origin: z.literal("https://quotes.toscrape.com"),
  instruction: textSchema.max(4_000),
  context: textSchema.max(4_000),
  page_count: z.literal(3),
  maximum_quote_count: z.literal(60),
  task_spec_sha256: sha256DigestSchema,
  executor_schema_version: z.literal("matraix-web-browser-executor/v1"),
  executor_spec_sha256: sha256DigestSchema,
  limitations: z.array(textSchema.max(4_000)).min(1),
}).strict();

const cohortSchema = z.object({
  id: uuidSchema,
  title: textSchema.max(200),
  cohort_sha256: sha256DigestSchema,
  dataset_sha256: sha256DigestSchema,
  persona_count: z.number().int().min(1).max(4),
}).strict();

const personaSchema = z.object({
  id: uuidSchema,
  position: z.number().int().min(0).max(3),
  persona_id: textSchema.max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u),
  display_name: textSchema.max(200),
  profile_sha256: sha256DigestSchema,
}).strict();

const quoteSchema = z.object({
  position: z.number().int().min(0).max(59),
  quote_id: sha256DigestSchema,
  text: textSchema.max(2_000),
  author: textSchema.max(200),
  tags: z.array(textSchema.max(128)).max(20),
}).strict();

const pageSchema = z.object({
  position: z.number().int().min(0).max(2),
  url: z.string().regex(/^https:\/\/quotes\.toscrape\.com\/(?:page\/[1-9][0-9]*\/)?$/u),
  title: textSchema.max(200),
  screenshot_sha256: sha256DigestSchema,
  screenshot_path: z.string().regex(/^\/api\/v2\/matraix\/web-trials\/[0-9a-f-]{36}\/screenshots\/[0-2]$/u),
  observed_at: timestampSchema,
  quotes: z.array(quoteSchema).min(1).max(20),
}).strict();

const resultSchema = z.object({
  runner_version: z.literal("1.0.0"),
  model_name: textSchema.max(200),
  web_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("matraix-web-quotes-choice/v1"),
  trace_sha256: sha256DigestSchema,
  result_sha256: sha256DigestSchema,
  decision_subject_id: sha256DigestSchema,
  decision_subject_label: textSchema.max(2_000),
  decision_outcome: z.literal("selected"),
  basis_primary: z.enum(["price", "quality", "features", "convenience", "taste", "trust", "familiarity", "novelty", "fit", "other"]),
  exploration_style: z.literal("compared_multiple"),
  reason: textSchema.min(20).max(2_000),
  task_author: textSchema.max(200),
  need_constraint_satisfaction: z.enum(["yes", "partially", "no"]),
  personal_preference_satisfaction: z.enum(["yes", "partially", "no"]),
  overall_experience_rating: z.number().int().min(1).max(10),
}).strict();

const errorSchema = z.object({
  code: textSchema.max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u),
  message: textSchema.max(4_000),
}).strict();

export const webTrialSchema = z.object({
  id: uuidSchema,
  status: statusSchema,
  persona: personaSchema,
  trial_sha256: sha256DigestSchema,
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  pages: z.array(pageSchema).max(3),
  result: resultSchema.nullable(),
  error: errorSchema.nullable(),
}).strict().superRefine((trial, context) => {
  if (!trial.pages.every((page, index) => page.position === index)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["pages"], message: "Page positions must be contiguous" });
  }
  const quotes = trial.pages.flatMap((page) => page.quotes);
  if (!quotes.every((quote, index) => quote.position === index)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["pages"], message: "Quote positions must be contiguous" });
  }
  const terminal = trial.status === "succeeded" || trial.status === "failed";
  if ((trial.status === "queued") !== (trial.started_at === null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["started_at"], message: "Started timestamp does not match status" });
  }
  if (terminal !== (trial.completed_at !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["completed_at"], message: "Completed timestamp does not match status" });
  }
  if (trial.status === "succeeded") {
    const quoteIds = new Set(quotes.map((quote) => quote.quote_id));
    if (trial.pages.length !== 3 || trial.result === null || trial.error !== null || !quoteIds.has(trial.result?.decision_subject_id ?? "")) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "Succeeded Web trial requires three observed pages and a selected observed quote" });
    }
  } else if (trial.result !== null) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["result"], message: "Only succeeded Web trials expose a result" });
  }
  if ((trial.status === "failed") !== (trial.error !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["error"], message: "Only failed Web trials expose an error" });
  }
});

const trialSummarySchema = z.object({
  id: uuidSchema,
  status: statusSchema,
  persona: personaSchema,
  trial_sha256: sha256DigestSchema,
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  observed_page_count: z.number().int().min(0).max(3),
  observed_quote_count: z.number().int().min(0).max(60),
  selected_quote_id: sha256DigestSchema.nullable(),
  error: errorSchema.nullable(),
}).strict().superRefine((trial, context) => {
  const terminal = trial.status === "succeeded" || trial.status === "failed";
  if ((trial.status === "queued") !== (trial.started_at === null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["started_at"], message: "Trial start does not match status" });
  }
  if (terminal !== (trial.completed_at !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["completed_at"], message: "Trial completion does not match status" });
  }
  if (trial.status === "succeeded") {
    if (trial.observed_page_count !== 3 || trial.observed_quote_count < 3 || trial.selected_quote_id === null || trial.error !== null) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "Succeeded Web trial summary is incomplete" });
    }
  } else if (trial.selected_quote_id !== null) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["selected_quote_id"], message: "Only succeeded Web trials expose a selected quote" });
  }
  if ((trial.status === "failed") !== (trial.error !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["error"], message: "Only failed Web trials expose an error" });
  }
});

const summaryObjectSchema = z.object({
  id: uuidSchema,
  status: statusSchema,
  created_at: timestampSchema,
  task: webTaskSchema,
  cohort: cohortSchema,
  trial_count: z.number().int().min(1).max(4),
  succeeded_trial_count: z.number().int().min(0).max(4),
  failed_trial_count: z.number().int().min(0).max(4),
  model_name: textSchema.max(200),
  web_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("matraix-web-quotes-choice/v1"),
  evaluation_sha256: sha256DigestSchema,
  retry_of_evaluation_id: uuidSchema.nullable(),
  retry_of_evaluation_sha256: sha256DigestSchema.nullable(),
  attempt_number: z.number().int().min(1).max(5),
}).strict();

export const webEvaluationSummarySchema = summaryObjectSchema.superRefine((value, context) => {
  if (value.trial_count !== value.cohort.persona_count || value.succeeded_trial_count + value.failed_trial_count > value.trial_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["trial_count"], message: "Evaluation counts must match the frozen Cohort" });
  }
  const hasParent = value.retry_of_evaluation_id !== null && value.retry_of_evaluation_sha256 !== null;
  if ((value.attempt_number === 1) === hasParent) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["attempt_number"], message: "Web retry lineage must match attempt number" });
  }
});

export const webEvaluationDetailSchema = summaryObjectSchema.extend({
  trials: z.array(trialSummarySchema).min(1).max(4),
}).strict().superRefine((value, context) => {
  const hasParent = value.retry_of_evaluation_id !== null && value.retry_of_evaluation_sha256 !== null;
  if ((value.attempt_number === 1) === hasParent) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["attempt_number"], message: "Web retry lineage must match attempt number" });
  }
  if (value.trials.length !== value.trial_count || !value.trials.every((trial, index) => trial.persona.position === index)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["trials"], message: "Trials must match frozen Persona order" });
  }
  const statuses = value.trials.map((trial) => trial.status);
  const succeededCount = statuses.filter((status) => status === "succeeded").length;
  const failedCount = statuses.filter((status) => status === "failed").length;
  if (succeededCount !== value.succeeded_trial_count || failedCount !== value.failed_trial_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["trials"], message: "Trial counts must match the evaluation summary" });
  }
  const expectedStatus = statuses.every((status) => status === "queued")
    ? "queued"
    : statuses.some((status) => status === "queued" || status === "running")
      ? "running"
      : statuses.every((status) => status === "succeeded")
        ? "succeeded"
        : "failed";
  if (value.status !== expectedStatus) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["status"], message: "Evaluation status must match trial summaries" });
  }
});

export const webEvaluationsResponseSchema = z.object({
  items: z.array(webEvaluationSummarySchema).max(50),
  page: z.number().int().positive(),
  page_size: z.number().int().min(1).max(50),
  total: z.number().int().nonnegative(),
}).strict();

export const webReadinessSchema = z.object({
  engine: z.literal("matraix-web-playwright"),
  runner_version: z.literal("1.0.0"),
  worker_online: z.boolean(),
  live_worker_count: z.number().int().nonnegative(),
  web_runtime_ready: z.boolean(),
  configuration_conflict: z.boolean(),
  model_name: textSchema.max(200).nullable(),
  web_config_sha256: sha256DigestSchema.nullable(),
  prompt_schema_version: z.literal("matraix-web-quotes-choice/v1").nullable(),
  task: webTaskSchema,
  limitations: z.array(textSchema.max(4_000)).min(1),
}).strict().superRefine((value, context) => {
  const complete = value.model_name !== null && value.web_config_sha256 !== null && value.prompt_schema_version !== null;
  if (value.web_runtime_ready !== complete || (value.web_runtime_ready && (!value.worker_online || value.configuration_conflict))) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["web_runtime_ready"], message: "Web readiness configuration is inconsistent" });
  }
});

const webTasksResponseSchema = z.object({ items: z.array(webTaskSchema).length(1), total: z.literal(1) }).strict();
const createRequestSchema = z.object({ cohort_id: uuidSchema, task_id: taskIdSchema, task_version: z.literal("1.0.0") }).strict();

export type WebTask = z.infer<typeof webTaskSchema>;
export type WebTrial = z.infer<typeof webTrialSchema>;
export type WebEvaluationSummary = z.infer<typeof webEvaluationSummarySchema>;
export type WebEvaluationDetail = z.infer<typeof webEvaluationDetailSchema>;
export type WebReadiness = z.infer<typeof webReadinessSchema>;

export function fetchWebTasks(signal: AbortSignal): Promise<z.infer<typeof webTasksResponseSchema>> {
  return getJson("/api/v2/matraix/web-tasks", webTasksResponseSchema, signal);
}

export function fetchWebReadiness(signal: AbortSignal): Promise<WebReadiness> {
  return getJson("/api/v2/matraix/web-readiness", webReadinessSchema, signal);
}

export function fetchWebEvaluations(page: number, signal: AbortSignal): Promise<z.infer<typeof webEvaluationsResponseSchema>> {
  return getJson(`/api/v2/matraix/web-evaluations?page=${page}&page_size=20`, webEvaluationsResponseSchema, signal);
}

export function fetchWebEvaluation(id: string, signal: AbortSignal): Promise<WebEvaluationDetail> {
  return getJson(`/api/v2/matraix/web-evaluations/${uuidSchema.parse(id)}`, webEvaluationDetailSchema, signal);
}

export function fetchWebEvaluationProgress(id: string, signal: AbortSignal): Promise<ParentProgress> {
  return getJson(
    `/api/v2/matraix/web-evaluations/${uuidSchema.parse(id)}/progress`,
    parentProgressSchema,
    signal,
  );
}

export function fetchWebTrial(id: string, signal: AbortSignal): Promise<WebTrial> {
  return getJson(`/api/v2/matraix/web-trials/${uuidSchema.parse(id)}`, webTrialSchema, signal);
}

export function createWebEvaluation(cohortId: string, signal: AbortSignal): Promise<WebEvaluationDetail> {
  const body = createRequestSchema.parse({ cohort_id: cohortId, task_id: "matraix/quotes-playwright-choice", task_version: "1.0.0" });
  return postJson("/api/v2/matraix/web-evaluations", body, webEvaluationDetailSchema, signal);
}

export function retryWebEvaluation(evaluationId: string, signal: AbortSignal): Promise<WebEvaluationDetail> {
  const id = uuidSchema.parse(evaluationId);
  return postJson(`/api/v2/matraix/web-evaluations/${id}/retry`, {}, webEvaluationDetailSchema, signal);
}
