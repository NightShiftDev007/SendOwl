import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const uuidSchema = z.string().uuid();
const textSchema = z.string().trim().min(1);
const timestampSchema = z.string().datetime({ offset: true });
const statusSchema = z.enum(["queued", "running", "succeeded", "failed"]);

export const linuxTaskSchema = z.object({
  task_id: z.literal("matraix/linux-note-to-csv"),
  version: z.literal("1.0.0"),
  schema_version: z.literal("matraix-linux-task/note-to-csv-v1"),
  title: z.literal("Note to CSV cleanup"),
  domain: z.literal("software"),
  source: z.object({
    kind: z.literal("source_sample"),
    project: z.literal("MatrAIx"),
    canonical_path: z.literal("application/tasks/example-computer-use-linux_note-to-csv"),
    production_sut: z.literal(false),
  }).strict(),
  execution_kind: z.literal("linux_artifact_runner"),
  computer_use: z.literal(false),
  instruction: textSchema.max(4_000),
  context: textSchema.max(4_000),
  required_artifacts: z.array(textSchema.max(128)).length(4),
  task_spec_sha256: sha256DigestSchema,
  runner_schema_version: z.literal("matraix-linux-artifact-runner/v1"),
  runner_spec_sha256: sha256DigestSchema,
  limitations: z.array(textSchema.max(4_000)).min(1),
}).strict();

const cohortSchema = z.object({
  id: uuidSchema,
  title: textSchema.max(200),
  cohort_sha256: sha256DigestSchema,
  dataset_sha256: sha256DigestSchema,
}).strict();

const personaSchema = z.object({
  id: uuidSchema,
  position: z.number().int().min(0).max(99),
  persona_id: textSchema.max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u),
  display_name: textSchema.max(200),
  profile_sha256: sha256DigestSchema,
}).strict();

const artifactHashesSchema = z.object({
  cleaned_list_csv: sha256DigestSchema,
  submission_json: sha256DigestSchema,
  user_feedback_json: sha256DigestSchema,
  verifier_json: sha256DigestSchema,
}).strict();

const resultSchema = z.object({
  runner_version: z.literal("1.0.0"),
  model_name: textSchema.max(200),
  linux_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("matraix-linux-note-to-csv/v1"),
  runner_schema_version: z.literal("matraix-linux-artifact-runner/v1"),
  runner_spec_sha256: sha256DigestSchema,
  verifier_passed: z.literal(true),
  rows_written: z.literal(3),
  artifact_sha256: sha256DigestSchema,
  file_sha256: artifactHashesSchema,
  result_sha256: sha256DigestSchema,
  reason: textSchema.min(10).max(2_000),
  need_constraint_satisfaction: z.enum(["yes", "partially", "no"]),
  personal_preference_satisfaction: z.enum(["yes", "partially", "no"]),
  overall_experience_rating: z.number().int().min(1).max(10),
  feedback_reason: textSchema.max(2_000),
}).strict();

const errorSchema = z.object({
  code: textSchema.max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u),
  message: textSchema.max(4_000),
}).strict();

export const linuxTrialSchema = z.object({
  id: uuidSchema,
  status: statusSchema,
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  task: linuxTaskSchema,
  cohort: cohortSchema,
  persona: personaSchema,
  trial_sha256: sha256DigestSchema,
  result: resultSchema.nullable(),
  error: errorSchema.nullable(),
}).strict().superRefine((value, context) => {
  const valid = value.status === "queued"
    ? value.started_at === null && value.completed_at === null && value.result === null && value.error === null
    : value.status === "running"
      ? value.started_at !== null && value.completed_at === null && value.result === null && value.error === null
      : value.status === "succeeded"
        ? value.started_at !== null && value.completed_at !== null && value.result !== null && value.error === null
        : value.started_at !== null && value.completed_at !== null && value.result === null && value.error !== null;
  if (!valid) context.addIssue({ code: z.ZodIssueCode.custom, message: "Linux trial lifecycle is inconsistent" });
});

export const linuxEvaluationSchema = z.object({
  id: uuidSchema,
  status: statusSchema,
  execution_kind: z.literal("linux_artifact_runner"),
  registry_eligibility: z.literal("sealed_parent"),
  created_at: timestampSchema,
  sealed_at: timestampSchema,
  evaluation_sha256: sha256DigestSchema,
  trial: linuxTrialSchema,
}).strict().superRefine((value, context) => {
  if (value.status !== value.trial.status) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["status"], message: "Evaluation status must match its trial" });
  }
  if (Date.parse(value.sealed_at) < Date.parse(value.created_at)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["sealed_at"], message: "Evaluation seal precedes creation" });
  }
});

export const linuxReadinessSchema = z.object({
  engine: z.literal("matraix-linux-artifact"),
  runner_version: z.literal("1.0.0"),
  worker_online: z.boolean(),
  live_worker_count: z.number().int().nonnegative(),
  linux_runtime_ready: z.boolean(),
  configuration_conflict: z.boolean(),
  model_name: textSchema.max(200).nullable(),
  linux_config_sha256: sha256DigestSchema.nullable(),
  prompt_schema_version: z.literal("matraix-linux-note-to-csv/v1").nullable(),
  task: linuxTaskSchema,
  limitations: z.array(textSchema.max(4_000)).min(1),
}).strict();

const trialsResponseSchema = z.object({
  items: z.array(linuxTrialSchema),
  page: z.number().int().positive(),
  page_size: z.number().int().min(1).max(50),
  total: z.number().int().nonnegative(),
}).strict();

export type LinuxTask = z.infer<typeof linuxTaskSchema>;
export type LinuxTrial = z.infer<typeof linuxTrialSchema>;
export type LinuxEvaluation = z.infer<typeof linuxEvaluationSchema>;
export type LinuxReadiness = z.infer<typeof linuxReadinessSchema>;

export async function fetchLinuxTasks(signal: AbortSignal): Promise<readonly LinuxTask[]> {
  const schema = z.object({ items: z.array(linuxTaskSchema).length(1), total: z.literal(1) }).strict();
  return (await getJson("/api/v2/matraix/linux-tasks", schema, signal)).items;
}

export async function fetchLinuxReadiness(signal: AbortSignal): Promise<LinuxReadiness> {
  return getJson("/api/v2/matraix/linux-readiness", linuxReadinessSchema, signal);
}

export async function fetchLinuxTrials(page: number, signal: AbortSignal): Promise<z.infer<typeof trialsResponseSchema>> {
  return getJson(`/api/v2/matraix/linux-trials?page=${page}&page_size=20`, trialsResponseSchema, signal);
}

export async function fetchLinuxTrial(id: string, signal: AbortSignal): Promise<LinuxTrial> {
  return getJson(`/api/v2/matraix/linux-trials/${uuidSchema.parse(id)}`, linuxTrialSchema, signal);
}

export async function fetchLinuxEvaluation(id: string, signal: AbortSignal): Promise<LinuxEvaluation> {
  return getJson(
    `/api/v2/matraix/linux-evaluations/${uuidSchema.parse(id)}`,
    linuxEvaluationSchema,
    signal,
  );
}

export async function createLinuxTrial(cohortId: string, personaId: string, signal: AbortSignal): Promise<LinuxTrial> {
  return postJson("/api/v2/matraix/linux-trials", {
    cohort_id: uuidSchema.parse(cohortId),
    persona_id: uuidSchema.parse(personaId),
    task_id: "matraix/linux-note-to-csv",
    task_version: "1.0.0",
  }, linuxTrialSchema, signal);
}

export async function createLinuxEvaluation(
  cohortId: string,
  personaId: string,
  signal: AbortSignal,
): Promise<LinuxEvaluation> {
  return postJson("/api/v2/matraix/linux-evaluations", {
    cohort_id: uuidSchema.parse(cohortId),
    persona_id: uuidSchema.parse(personaId),
    task_id: "matraix/linux-note-to-csv",
    task_version: "1.0.0",
  }, linuxEvaluationSchema, signal);
}
