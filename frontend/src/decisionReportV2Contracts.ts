import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const endpoint = "/api/v2/decision-reports/v2";
const uuidSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const dateSchema = z.string().date();
const digestSchema = sha256DigestSchema;
const shortTextSchema = z.string().trim().min(1);
const titleSchema = z.string().trim().min(1).max(300).regex(/^[^\r\n]+$/u);

const v2SnapshotRefSchema = z.object({
  world_model_id: uuidSchema,
  world_snapshot_id: uuidSchema,
  version: z.number().int().min(1),
  snapshot_sha256: digestSchema,
  created_at: timestampSchema,
  sealed_at: timestampSchema,
  verification: z.literal("human_confirmed"),
}).strict();

const v2EvidenceSourceSchema = z.object({
  evidence_kind: z.enum(["media_article", "policy_document"]),
  source_id: uuidSchema,
  source_name: z.string().trim().min(1).max(300),
  original_url: z.string().url(),
  title: z.string().trim().min(1).max(500),
  published_at: timestampSchema.nullable(),
  publication_date: dateSchema.nullable(),
  captured_at: timestampSchema,
  content_sha256: digestSchema,
  identity_sha256: digestSchema,
  excerpt: z.string().min(1).max(280),
}).strict();

const v2EvidencePayloadSchema = z.object({
  payload_kind: z.literal("evidence"),
  world_snapshot: v2SnapshotRefSchema,
  sources: z.array(v2EvidenceSourceSchema).min(1).max(50),
  evidence_boundary: z.object({
    status: z.literal("frozen_source_copy_not_independent_fact_check"),
    statements: z.array(shortTextSchema).min(1).max(10),
  }).strict(),
}).strict();

const v2InterventionSchema = z.object({
  id: uuidSchema,
  kind: z.literal("initial_post"),
  actor: z.literal("scenario_actor"),
  channel: z.literal("reddit"),
  content: z.string().trim().min(1).max(4_000),
  offset_minutes: z.number().int().min(0).max(1_440),
  provenance: z.literal("scenario_assumption"),
  synthetic_label: z.string().trim().min(1).max(64).nullable(),
}).strict();

const v2VariantSchema = z.object({
  id: uuidSchema,
  position: z.number().int().min(0).max(5),
  role: z.enum(["baseline", "alternative"]),
  name: z.string().trim().min(1).max(200),
  hypothesis: z.string().trim().min(1).max(2_000),
  interventions: z.array(v2InterventionSchema),
}).strict();

const v2AssumptionsPayloadSchema = z.object({
  payload_kind: z.literal("assumptions"),
  scenario: z.object({
    id: uuidSchema,
    scenario_sha256: digestSchema,
    title: titleSchema,
    decision_question: z.string().trim().min(1).max(2_000),
    world_snapshot_id: uuidSchema,
    snapshot_sha256: digestSchema,
    variants: z.array(v2VariantSchema).min(2).max(3),
  }).strict(),
  assumption_boundary: z.array(shortTextSchema).min(1).max(10),
}).strict();

const v2TrialSchema = z.object({
  id: uuidSchema,
  variant_id: uuidSchema,
  role: z.enum(["baseline", "alternative"]),
  seed: z.number().int().min(0).max(4_294_967_295),
  trial_sha256: digestSchema,
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  artifact_sha256: digestSchema.nullable(),
  rounds_completed: z.number().int().min(1).max(3).nullable(),
  failure: z.object({
    code: shortTextSchema,
    message: z.string().trim().min(1).max(4_000),
  }).strict().nullable(),
}).strict();

const v2ExperimentPayloadSchema = z.object({
  payload_kind: z.literal("experiment"),
  experiment: z.object({
    id: uuidSchema,
    experiment_sha256: digestSchema,
    status: z.enum(["queued", "running", "succeeded", "failed"]),
    scenario_id: uuidSchema,
    scenario_sha256: digestSchema,
    cohort_id: uuidSchema,
    cohort_sha256: digestSchema,
    dataset_sha256: digestSchema,
    persona_count: z.number().int().min(1).max(8),
    variants: z.array(v2VariantSchema).min(2).max(3),
    seeds: z.array(z.number().int().min(0).max(4_294_967_295)).min(1).max(2),
    rounds: z.number().int().min(1).max(3),
    minutes_per_round: z.number().int().min(15).max(240),
    model_name: shortTextSchema.max(200),
    semantic_config_sha256: digestSchema,
    prompt_schema_version: z.literal("matraix-semantic-profile/v1"),
    engine_version: shortTextSchema.max(32).nullable(),
    camel_version: shortTextSchema.max(32).nullable(),
  }).strict(),
  trials: z.array(v2TrialSchema).min(2).max(6),
}).strict();

const v2ObservationPayloadSchema = z.object({
  payload_kind: z.literal("observation"),
  trials: z.array(z.object({
    trial_id: uuidSchema,
    variant_id: uuidSchema,
    seed: z.number().int().min(0).max(4_294_967_295),
    status: z.enum(["queued", "running", "succeeded", "failed"]),
    event_count: z.number().int().nonnegative(),
    events_sha256: digestSchema,
    event_endpoint: z.string().trim().min(1).max(300),
    normalized_counts: z.object({
      scenario_initial_posts: z.number().int().nonnegative(),
      generated_posts: z.number().int().nonnegative(),
      comments: z.number().int().nonnegative(),
      reactions: z.number().int().nonnegative(),
      do_nothing: z.number().int().nonnegative(),
      observed_actions: z.number().int().nonnegative(),
      authored_content: z.number().int().nonnegative(),
    }).strict(),
    event_clock_boundary: z.object({
      observed_at_raw_semantics: shortTextSchema.max(500),
      recorded_at_semantics: shortTextSchema.max(500),
    }).strict(),
  }).strict()).min(2).max(6),
  behavior_changes: z.array(z.object({
    statement: z.string().trim().min(1).max(2_000),
    basis: z.array(shortTextSchema).min(1).max(10),
  }).strict()).min(1).max(20),
}).strict();

const metricNameSchema = z.enum([
  "observed_action_count",
  "authored_content_count",
  "reaction_count",
  "do_nothing_count",
]);

const v2ComparisonPayloadSchema = z.object({
  payload_kind: z.literal("comparison"),
  metrics: z.array(z.object({
    metric: metricNameSchema,
    variants: z.array(z.object({
      variant_id: uuidSchema,
      name: z.string().trim().min(1).max(200),
      role: z.enum(["baseline", "alternative"]),
      mean: z.number().finite(),
      stddev: z.number().finite().nonnegative(),
      n: z.number().int().min(1).max(2),
    }).strict()).min(2).max(3),
    alternatives: z.array(z.object({
      variant_id: uuidSchema,
      name: z.string().trim().min(1).max(200),
      mean: z.number().finite(),
      stddev: z.number().finite().nonnegative(),
      n: z.number().int().min(1).max(2),
      mean_delta: z.number().finite(),
      stddev_delta: z.number().finite().nonnegative(),
      paired_seeds: z.array(z.number().int().min(0).max(4_294_967_295)).min(1).max(2),
      paired_seed_count: z.number().int().min(1).max(2),
    }).strict()).min(1).max(2),
  }).strict()),
  comparison_state: z.enum(["pending", "partial", "complete", "failed"]),
  pairing_rule: shortTextSchema.max(500),
  comparison_boundary: z.array(shortTextSchema).min(1).max(10),
}).strict();

const v2AnalysisPayloadSchema = z.object({
  payload_kind: z.literal("analysis"),
  statements: z.array(z.object({
    statement_id: shortTextSchema.max(128),
    text: z.string().trim().min(1).max(2_000),
    basis: z.array(shortTextSchema).min(1).max(10),
    allowed_type: z.enum(["accounting_explanation", "scope_explanation", "boundary_explanation"]),
  }).strict()).min(1).max(20),
  prohibited_claims: z.array(shortTextSchema).min(1).max(10),
}).strict();

const v2LimitationsPayloadSchema = z.object({
  payload_kind: z.literal("limitations"),
  items: z.array(z.object({
    code: z.enum([
      "sample_size",
      "synthetic_inputs",
      "model_dependency",
      "simulation_boundary",
      "evidence_boundary",
      "clock_semantics",
      "no_prediction_or_recommendation",
    ]),
    text: z.string().trim().min(1).max(2_000),
    severity: z.enum(["material", "context"]),
  }).strict()).min(1).max(10),
}).strict();

export const decisionReportV2PayloadSchema = z.discriminatedUnion("payload_kind", [
  v2EvidencePayloadSchema,
  v2AssumptionsPayloadSchema,
  v2ExperimentPayloadSchema,
  v2ObservationPayloadSchema,
  v2ComparisonPayloadSchema,
  v2AnalysisPayloadSchema,
  v2LimitationsPayloadSchema,
]);

export const decisionReportV2SectionSchema = z.object({
  position: z.number().int().min(0).max(6),
  kind: z.enum([
    "evidence",
    "assumptions",
    "experiment",
    "observation",
    "comparison",
    "analysis",
    "limitations",
  ]),
  title: titleSchema,
  body_markdown: z.string().min(1).max(40_000),
  data: decisionReportV2PayloadSchema,
}).strict().superRefine((value, context) => {
  if (value.kind !== value.data.payload_kind) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "V2 section kind does not match payload_kind" });
  }
});

export const decisionReportV2Schema = z.object({
  id: uuidSchema,
  experiment_id: uuidSchema,
  experiment_sha256: digestSchema,
  scenario_id: uuidSchema,
  scenario_sha256: digestSchema,
  cohort_id: uuidSchema,
  cohort_sha256: digestSchema,
  world_snapshot_id: uuidSchema,
  world_snapshot_sha256: digestSchema,
  title: titleSchema,
  report_sha256: digestSchema,
  generator_version: z.literal("decision-report/v2"),
  created_at: timestampSchema,
  sections: z.array(decisionReportV2SectionSchema).length(7),
}).strict().superRefine((value, context) => {
  const positions = value.sections.map((section) => section.position);
  const kinds = value.sections.map((section) => section.kind);
  if (positions.join(",") !== "0,1,2,3,4,5,6") {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "V2 report sections must be contiguous" });
  }
  if (kinds.join(",") !== "evidence,assumptions,experiment,observation,comparison,analysis,limitations") {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "V2 report outline is invalid" });
  }
});

export const decisionReportsV2ResponseSchema = z.object({
  items: z.array(decisionReportV2Schema),
  total: z.number().int().nonnegative(),
}).strict();

export type DecisionReportV2 = z.infer<typeof decisionReportV2Schema>;
export type DecisionReportV2Section = z.infer<typeof decisionReportV2SectionSchema>;
export type DecisionReportV2Payload = z.infer<typeof decisionReportV2PayloadSchema>;
export type DecisionReportsV2Response = z.infer<typeof decisionReportsV2ResponseSchema>;

export function fetchDecisionReportsV2(signal: AbortSignal): Promise<DecisionReportsV2Response> {
  return getJson(endpoint, decisionReportsV2ResponseSchema, signal);
}

export function fetchDecisionReportV2(
  reportId: string,
  signal: AbortSignal,
): Promise<DecisionReportV2> {
  return getJson(
    `${endpoint}/${encodeURIComponent(reportId)}`,
    decisionReportV2Schema,
    signal,
  );
}

export function generateDecisionReportV2(
  experimentId: string,
  signal: AbortSignal,
): Promise<DecisionReportV2> {
  return postJson(
    `${endpoint}/from-experiment/${encodeURIComponent(experimentId)}`,
    {},
    decisionReportV2Schema,
    signal,
  );
}

export function createDecisionReportV2MarkdownUrl(reportId: string): string {
  return `${endpoint}/${encodeURIComponent(reportId)}/markdown`;
}
