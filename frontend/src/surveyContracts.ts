import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";
import { parentProgressSchema, type ParentProgress } from "./parentProgress";

const experimentsEndpoint = "/api/v2/matraix/survey-experiments";
const trialsEndpoint = "/api/v2/matraix/survey-trials";
const readinessEndpoint = "/api/v2/matraix/survey-readiness";
const identifierSchema = z.string().uuid();
const pageSchema = z.number().int().positive();
const timestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const singleLineTextSchema = nonEmptyTextSchema.regex(/^[^\r\n]+$/u);
const statusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const promptSchemaVersionSchema = z.literal("matraix-survey-scenario-preference/v1");
const instrumentSchemaVersionSchema = z.literal("scenario-preference/v1");

export const surveyScenarioRefSchema = z.object({
  id: identifierSchema,
  title: singleLineTextSchema.max(300),
  decision_question: nonEmptyTextSchema.max(2_000),
  scenario_sha256: sha256DigestSchema,
}).strict();

export const surveyCohortRefSchema = z.object({
  id: identifierSchema,
  title: singleLineTextSchema.max(200),
  cohort_sha256: sha256DigestSchema,
  dataset_sha256: sha256DigestSchema,
  persona_count: z.number().int().min(1).max(8),
}).strict();

export const surveyVariantRefSchema = z.object({
  id: identifierSchema,
  role: z.enum(["baseline", "alternative"]),
  position: z.number().int().nonnegative().max(5),
  name: singleLineTextSchema.max(200),
  hypothesis: nonEmptyTextSchema.max(2_000),
}).strict().superRefine((variant, context) => {
  if ((variant.role === "baseline") !== (variant.position === 0)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["position"],
      message: "Baseline must use position zero and alternatives must use a positive position",
    });
  }
});

export const surveyPersonaRefSchema = z.object({
  id: identifierSchema,
  position: z.number().int().min(0).max(7),
  persona_id: singleLineTextSchema.max(128),
  display_name: nonEmptyTextSchema.max(200),
  profile_sha256: sha256DigestSchema,
}).strict();

const surveyOptionSchema = z.object({
  id: z.enum(["baseline", "alternative"]),
  label: singleLineTextSchema.max(200),
  description: nonEmptyTextSchema.max(2_000),
}).strict();

const choiceQuestionSchema = z.object({
  position: z.literal(0),
  id: z.literal("preferred_variant"),
  type: z.literal("single_choice"),
  prompt: nonEmptyTextSchema.max(4_000),
  required: z.literal(true),
  options: z.tuple([
    surveyOptionSchema.extend({ id: z.literal("baseline") }).strict(),
    surveyOptionSchema.extend({ id: z.literal("alternative") }).strict(),
  ]),
  min_value: z.null(),
  max_value: z.null(),
}).strict();

const likertQuestionSchema = z.object({
  position: z.literal(1),
  id: z.literal("alternative_support"),
  type: z.literal("likert"),
  prompt: nonEmptyTextSchema.max(4_000),
  required: z.literal(true),
  options: z.tuple([]),
  min_value: z.literal(1),
  max_value: z.literal(5),
}).strict();

const freeTextQuestionSchema = z.object({
  position: z.literal(2),
  id: z.literal("primary_reason"),
  type: z.literal("free_text"),
  prompt: nonEmptyTextSchema.max(4_000),
  required: z.literal(true),
  options: z.tuple([]),
  min_value: z.null(),
  max_value: z.null(),
}).strict();

export const surveyInstrumentSchema = z.object({
  schema_version: instrumentSchemaVersionSchema,
  instrument_sha256: sha256DigestSchema,
  title: z.literal("Scenario preference"),
  description: nonEmptyTextSchema,
  questions: z.tuple([choiceQuestionSchema, likertQuestionSchema, freeTextQuestionSchema]),
}).strict();

const surveyExperimentSummaryObjectSchema = z.object({
  id: identifierSchema,
  status: statusSchema,
  created_at: timestampSchema,
  scenario: surveyScenarioRefSchema,
  cohort: surveyCohortRefSchema,
  baseline: surveyVariantRefSchema,
  alternative: surveyVariantRefSchema,
  trial_count: z.number().int().min(1).max(8),
  succeeded_trial_count: z.number().int().min(0).max(8),
  failed_trial_count: z.number().int().min(0).max(8),
  model_name: singleLineTextSchema.max(200),
  survey_config_sha256: sha256DigestSchema,
  prompt_schema_version: promptSchemaVersionSchema,
  instrument_schema_version: instrumentSchemaVersionSchema,
  instrument_sha256: sha256DigestSchema,
  experiment_sha256: sha256DigestSchema,
  retry_of_experiment_id: identifierSchema.nullable(),
  retry_of_experiment_sha256: sha256DigestSchema.nullable(),
  attempt_number: z.number().int().min(1).max(5),
}).strict();

export const surveyExperimentSummarySchema = surveyExperimentSummaryObjectSchema.superRefine((experiment, context) => {
  const hasParent = experiment.retry_of_experiment_id !== null && experiment.retry_of_experiment_sha256 !== null;
  if ((experiment.attempt_number === 1) === hasParent) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["attempt_number"], message: "Survey retry lineage must match attempt number" });
  }
  if (experiment.trial_count !== experiment.cohort.persona_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["trial_count"], message: "Trial count must equal the frozen Cohort size" });
  }
  if (experiment.succeeded_trial_count + experiment.failed_trial_count > experiment.trial_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["failed_trial_count"], message: "Terminal trial counts cannot exceed trial_count" });
  }
  if (experiment.baseline.role !== "baseline" || experiment.alternative.role !== "alternative") {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["alternative"], message: "Experiment variants must bind baseline and alternative roles" });
  }
});

const choiceAnswerSchema = z.object({
  position: z.literal(0),
  question_id: z.literal("preferred_variant"),
  type: z.literal("single_choice"),
  value: z.enum(["baseline", "alternative"]),
}).strict();
const likertAnswerSchema = z.object({
  position: z.literal(1),
  question_id: z.literal("alternative_support"),
  type: z.literal("likert"),
  value: z.number().int().min(1).max(5),
}).strict();
const freeTextAnswerSchema = z.object({
  position: z.literal(2),
  question_id: z.literal("primary_reason"),
  type: z.literal("free_text"),
  value: nonEmptyTextSchema.max(2_000),
}).strict();

export const surveyTrialResultSchema = z.object({
  runner_version: z.literal("1.0.0"),
  model_name: singleLineTextSchema.max(200),
  survey_config_sha256: sha256DigestSchema,
  prompt_schema_version: promptSchemaVersionSchema,
  answers_sha256: sha256DigestSchema,
  answers: z.tuple([choiceAnswerSchema, likertAnswerSchema, freeTextAnswerSchema]),
}).strict();

export const surveyTrialSchema = z.object({
  id: identifierSchema,
  status: statusSchema,
  persona: surveyPersonaRefSchema,
  trial_sha256: sha256DigestSchema,
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  result: surveyTrialResultSchema.nullable(),
  error: z.object({ code: singleLineTextSchema.max(128), message: nonEmptyTextSchema.max(4_000) }).strict().nullable(),
}).strict().superRefine((trial, context) => {
  if ((trial.status === "succeeded") !== (trial.result !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["result"], message: "Only succeeded trials may expose a result" });
  }
  if ((trial.status === "failed") !== (trial.error !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["error"], message: "Only failed trials may expose an error" });
  }
  if (["succeeded", "failed"].includes(trial.status) !== (trial.completed_at !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["completed_at"], message: "Only terminal trials must have completed_at" });
  }
  if ((trial.status !== "queued") !== (trial.started_at !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["started_at"], message: "Every claimed trial must have started_at" });
  }
});

export const surveyAggregateSchema = z.object({
  succeeded_trial_count: z.number().int().min(0).max(8),
  failed_trial_count: z.number().int().min(0).max(8),
  preferred_variant: z.object({ baseline_count: z.number().int().min(0).max(8), alternative_count: z.number().int().min(0).max(8) }).strict(),
  alternative_support: z.object({ n: z.number().int().min(0).max(8), min: z.number().int().min(1).max(5).nullable(), max: z.number().int().min(1).max(5).nullable(), mean: z.number().finite().min(1).max(5).nullable() }).strict(),
  primary_reasons: z.array(z.object({ trial_id: identifierSchema, persona: surveyPersonaRefSchema, text: nonEmptyTextSchema.max(2_000) }).strict()).max(8),
  limitations: z.array(nonEmptyTextSchema).min(1),
}).strict().superRefine((aggregate, context) => {
  const choiceTotal = aggregate.preferred_variant.baseline_count + aggregate.preferred_variant.alternative_count;
  if (choiceTotal !== aggregate.succeeded_trial_count || aggregate.alternative_support.n !== aggregate.succeeded_trial_count || aggregate.primary_reasons.length !== aggregate.succeeded_trial_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Every succeeded trial must contribute exactly one typed answer to each aggregate" });
  }
  const hasRange = aggregate.alternative_support.n > 0;
  if (hasRange !== (aggregate.alternative_support.min !== null && aggregate.alternative_support.max !== null && aggregate.alternative_support.mean !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["alternative_support"], message: "Likert range is present exactly when n is positive" });
  }
});

export const surveyExperimentDetailSchema = surveyExperimentSummaryObjectSchema.extend({
  instrument: surveyInstrumentSchema,
  trials: z.array(surveyTrialSchema).min(1).max(8),
  aggregate: surveyAggregateSchema,
}).strict().superRefine((experiment, context) => {
  if (experiment.trial_count !== experiment.cohort.persona_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["trial_count"], message: "Trial count must equal the frozen Cohort size" });
  }
  if (experiment.succeeded_trial_count + experiment.failed_trial_count > experiment.trial_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["failed_trial_count"], message: "Terminal trial counts cannot exceed trial_count" });
  }
  if (experiment.baseline.role !== "baseline" || experiment.alternative.role !== "alternative") {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["alternative"], message: "Experiment variants must bind baseline and alternative roles" });
  }
  if (experiment.trials.length !== experiment.trial_count || !experiment.trials.every((trial, index) => trial.persona.position === index)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["trials"], message: "Trials must cover the Cohort in contiguous Persona order" });
  }
  if (experiment.instrument.instrument_sha256 !== experiment.instrument_sha256) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["instrument"], message: "Instrument must match the frozen experiment digest" });
  }
  if (experiment.aggregate.succeeded_trial_count !== experiment.succeeded_trial_count || experiment.aggregate.failed_trial_count !== experiment.failed_trial_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["aggregate"], message: "Aggregate terminal counts must match the experiment" });
  }
});

export const surveyExperimentsResponseSchema = z.object({
  items: z.array(surveyExperimentSummarySchema).max(50),
  page: z.number().int().positive(),
  page_size: z.number().int().min(1).max(50),
  total: z.number().int().nonnegative(),
}).strict();

export const surveyReadinessSchema = z.object({
  engine: z.literal("matraix-survey"),
  runner_version: z.literal("1.0.0"),
  worker_online: z.boolean(),
  live_worker_count: z.number().int().nonnegative(),
  survey_runtime_ready: z.boolean(),
  configuration_conflict: z.boolean(),
  model_name: singleLineTextSchema.max(200).nullable(),
  survey_config_sha256: sha256DigestSchema.nullable(),
  prompt_schema_version: promptSchemaVersionSchema.nullable(),
  instrument_schema_version: instrumentSchemaVersionSchema,
  limitations: z.array(nonEmptyTextSchema).min(1),
}).strict().superRefine((readiness, context) => {
  const hasConfig = readiness.model_name !== null && readiness.survey_config_sha256 !== null && readiness.prompt_schema_version !== null;
  if (readiness.survey_runtime_ready !== hasConfig) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["survey_runtime_ready"], message: "Runtime readiness must match a complete live configuration identity" });
  }
  if (readiness.worker_online !== (readiness.live_worker_count > 0)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["worker_online"], message: "worker_online must equal live_worker_count > 0" });
  }
  if (!readiness.survey_runtime_ready && hasConfig) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["model_name"], message: "An unready projection must not expose a selected Survey configuration" });
  }
  if (readiness.survey_runtime_ready && (!readiness.worker_online || readiness.configuration_conflict || readiness.live_worker_count < 1)) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["survey_runtime_ready"], message: "Ready Survey runtime requires a live, conflict-free worker" });
  }
});

export const surveyExperimentCreateRequestSchema = z.object({
  scenario_id: identifierSchema,
  cohort_id: identifierSchema,
  alternative_id: identifierSchema,
}).strict();

export type SurveyExperimentSummary = z.infer<typeof surveyExperimentSummarySchema>;
export type SurveyExperimentDetail = z.infer<typeof surveyExperimentDetailSchema>;
export type SurveyTrial = z.infer<typeof surveyTrialSchema>;
export type SurveyReadiness = z.infer<typeof surveyReadinessSchema>;
export type SurveyExperimentCreateRequest = z.infer<typeof surveyExperimentCreateRequestSchema>;

export function fetchSurveyReadiness(signal: AbortSignal): Promise<SurveyReadiness> {
  return getJson(readinessEndpoint, surveyReadinessSchema, signal);
}
export function fetchSurveyExperiments(page: number, signal: AbortSignal): Promise<z.infer<typeof surveyExperimentsResponseSchema>> {
  const parsedPage = pageSchema.parse(page);
  return getJson(`${experimentsEndpoint}?page=${parsedPage}&page_size=20`, surveyExperimentsResponseSchema, signal);
}
export function fetchSurveyExperiment(experimentId: string, signal: AbortSignal): Promise<SurveyExperimentDetail> {
  const id = identifierSchema.parse(experimentId);
  return getJson(`${experimentsEndpoint}/${encodeURIComponent(id)}`, surveyExperimentDetailSchema, signal);
}
export function fetchSurveyExperimentProgress(experimentId: string, signal: AbortSignal): Promise<ParentProgress> {
  const id = identifierSchema.parse(experimentId);
  return getJson(`${experimentsEndpoint}/${encodeURIComponent(id)}/progress`, parentProgressSchema, signal);
}
export function fetchSurveyTrial(trialId: string, signal: AbortSignal): Promise<SurveyTrial> {
  const id = identifierSchema.parse(trialId);
  return getJson(`${trialsEndpoint}/${encodeURIComponent(id)}`, surveyTrialSchema, signal);
}
export function createSurveyExperiment(request: SurveyExperimentCreateRequest, signal: AbortSignal): Promise<SurveyExperimentDetail> {
  const body = surveyExperimentCreateRequestSchema.parse(request);
  return postJson(experimentsEndpoint, body, surveyExperimentDetailSchema, signal);
}
export function retrySurveyExperiment(experimentId: string, signal: AbortSignal): Promise<SurveyExperimentDetail> {
  const id = identifierSchema.parse(experimentId);
  return postJson(`${experimentsEndpoint}/${encodeURIComponent(id)}/retry`, {}, surveyExperimentDetailSchema, signal);
}
