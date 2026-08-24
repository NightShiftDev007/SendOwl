import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const endpoint = "/api/v2/research-projects";
const identifierSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const singleLineSchema = z.string().trim().min(1).max(300).regex(/^[^\r\n]+$/u);
const textSchema = z.string().trim().min(1);

const snapshotRefSchema = z.object({
  world_model_id: identifierSchema,
  world_snapshot_id: identifierSchema,
  snapshot_sha256: sha256DigestSchema,
}).strict();

const cohortRefSchema = z.object({
  cohort_id: identifierSchema,
  cohort_sha256: sha256DigestSchema,
  persona_count: z.number().int().min(1).max(100),
}).strict();

const graphRefSchema = z.object({
  graph_id: identifierSchema,
  graph_sha256: sha256DigestSchema,
  node_count: z.number().int().min(1).max(500),
  edge_count: z.number().int().min(0).max(2000),
}).strict();

export const researchProjectSchema = z.object({
  id: identifierSchema,
  title: singleLineSchema,
  research_question: textSchema.max(2000),
  snapshot: snapshotRefSchema,
  graph: graphRefSchema.nullable(),
  schema_version: z.enum([
    "sandowl-research-project/v1",
    "sandowl-research-project/v2",
    "sandowl-research-project/v3",
  ]),
  legacy_design: z.object({
    cohort: cohortRefSchema,
    simulation_requirement: textSchema.max(4000),
  }).strict().nullable(),
  project_sha256: sha256DigestSchema,
  created_at: timestampSchema,
}).strict();

export const researchProjectsResponseSchema = z.object({
  items: z.array(researchProjectSchema),
  total: z.number().int().nonnegative(),
}).strict();

export const researchProjectCreateRequestSchema = z.object({
  title: singleLineSchema,
  research_question: textSchema.max(2000),
  world_model_id: identifierSchema,
  world_snapshot_id: identifierSchema,
  world_graph_id: identifierSchema,
}).strict();

export type ResearchProject = z.infer<typeof researchProjectSchema>;
export type ResearchProjectsResponse = z.infer<typeof researchProjectsResponseSchema>;
export type ResearchProjectCreateRequest = z.infer<typeof researchProjectCreateRequestSchema>;

const researchAgendaSnapshotSchema = z.object({
  country_code: z.string().length(2),
  window_start: timestampSchema,
  window_end: timestampSchema,
  granularity: z.enum(["hour", "day", "week"]),
  article_count: z.number().int().nonnegative(),
  salience_score: z.number().nonnegative(),
  salience_rank: z.number().int().positive(),
}).strict();

const researchAgendaPropagationEdgeSchema = z.object({
  position: z.number().int().nonnegative(),
  from_country_code: z.string().length(2),
  to_country_code: z.string().length(2),
  lag_hours: z.number().nonnegative(),
  first_media_name: z.string().nullable(),
  first_article_id: identifierSchema.nullable(),
  first_published_at: timestampSchema.nullable(),
  observation_source: z.enum(["legacy_projection", "structured_followers", "native_collection"]),
}).strict();

const researchAgendaPropagationEventSchema = z.object({
  id: identifierSchema,
  status: z.enum(["watching", "suspected", "confirmed", "dismissed", "revised", "archived"]),
  confidence: z.enum(["watching", "suspected", "confirmed"]),
  origin_country_code: z.string().length(2),
  origin_source_name: z.string().nullable(),
  origin_at: timestampSchema,
  origin_confidence: z.enum(["high", "medium", "low"]),
  detection_method: textSchema,
  edges: z.array(researchAgendaPropagationEdgeSchema).max(20),
}).strict();

const researchAgendaFirstUtteranceSchema = z.object({
  id: identifierSchema,
  entity_name: textSchema.max(200),
  entity_type: z.enum(["person", "thinktank", "intl_org", "gov_body"]),
  country_code: z.string().length(2),
  article_id: identifierSchema,
  occurred_at: timestampSchema.nullable(),
  evidence_quote: textSchema.max(2000),
  model_name: textSchema.max(200),
  prompt_version: textSchema.max(100),
}).strict();

const researchAgendaTopicSchema = z.object({
  id: identifierSchema,
  name: textSchema.max(300),
  summary: z.string().nullable(),
  category: z.string().nullable(),
  status: z.enum(["emerging", "heating", "stable", "declining", "archived"]),
  lifecycle_state: z.enum(["nascent", "forming", "confirmed", "evolving", "archived"]),
  first_seen_at: timestampSchema,
  last_seen_at: timestampSchema,
  linked_article_ids: z.array(identifierSchema).min(1).max(50),
  salience: z.array(researchAgendaSnapshotSchema).max(24),
  propagation: z.array(researchAgendaPropagationEventSchema).max(10),
  first_utterances: z.array(researchAgendaFirstUtteranceSchema).max(10),
}).strict();

export const researchProjectAgendaContextSchema = z.object({
  project_id: identifierSchema,
  project_sha256: sha256DigestSchema,
  payload: z.object({
    schema_version: z.literal("sandowl-project-agenda-context/v1"),
    snapshot_sha256: sha256DigestSchema,
    frozen_article_ids: z.array(identifierSchema).min(1).max(50),
    topics: z.array(researchAgendaTopicSchema).max(50),
    source_sync_run_id: identifierSchema.nullable(),
    source_observed_at: timestampSchema.nullable(),
    limitations: z.array(textSchema).min(1),
  }).strict(),
  context_sha256: sha256DigestSchema,
  captured_at: timestampSchema,
}).strict();

export type ResearchProjectAgendaContext = z.infer<typeof researchProjectAgendaContextSchema>;

const runResultSchema = z.object({
  artifact_sha256: sha256DigestSchema,
  artifact_size_bytes: z.number().int().positive(),
  user_count: z.number().int().min(2).max(9),
  initial_post_count: z.number().int().min(1).max(6),
  generated_post_count: z.number().int().nonnegative(),
  comment_count: z.number().int().nonnegative(),
  reaction_count: z.number().int().nonnegative(),
  do_nothing_count: z.number().int().nonnegative(),
  observed_action_count: z.number().int().positive(),
  rounds_completed: z.number().int().min(1).max(6),
  limitations: z.array(textSchema),
}).strict();

const runErrorSchema = z.object({
  code: z.string().min(1).max(128),
  message: z.string().min(1).max(4000),
}).strict();

const simulationContextSchema = z.object({
  schema_version: z.literal("sandowl-simulation-context/v1"),
  snapshot_sha256: sha256DigestSchema,
  graph: graphRefSchema,
  media_items: z.array(z.object({
    position: z.number().int().min(0).max(9),
    article_id: identifierSchema,
    title: textSchema.max(1000),
    source_name: textSchema.max(500),
    excerpt: textSchema.max(1000),
  }).strict()).min(1).max(10),
  policy_items: z.array(z.object({
    position: z.number().int().min(0).max(9),
    policy_version_id: identifierSchema,
    title: textSchema.max(1000),
    authority_name: textSchema.max(500),
    jurisdiction_code: z.string().min(2).max(16),
  }).strict()).max(10),
  nodes: z.array(z.object({
    position: z.number().int().min(0).max(19),
    node_id: identifierSchema,
    entity_type: textSchema.max(32),
    name: textSchema.max(200),
    summary: textSchema.max(500),
    evidence_quote: textSchema.max(500),
  }).strict()).min(1).max(20),
  edges: z.array(z.object({
    position: z.number().int().min(0).max(29),
    edge_id: identifierSchema,
    source_name: textSchema.max(200),
    relation_type: textSchema.max(64),
    target_name: textSchema.max(200),
    fact: textSchema.max(500),
    evidence_quote: textSchema.max(500),
  }).strict()).max(30),
  total_media_count: z.number().int().min(1).max(50),
  total_policy_count: z.number().int().min(0).max(50),
  total_node_count: z.number().int().min(1).max(500),
  total_edge_count: z.number().int().min(0).max(2000),
  truncated: z.boolean(),
}).strict();

const scheduledPostSchema = z.object({
  position: z.number().int().min(0).max(5),
  content: textSchema.max(4000),
  offset_minutes: z.number().int().min(0).max(2880),
  source: z.literal("user_synthetic"),
}).strict();

export const researchSimulationPlanSchema = z.object({
  schema_version: z.literal("sandowl-simulation-plan/v1"),
  planning_mode: z.enum(["manual", "automatic"]),
  planner_version: z.enum(["manual/v1", "deterministic-context-planner/v1"]),
  platform: z.literal("reddit"),
  activity_intensity: z.enum(["manual", "low", "standard", "high"]),
  context_item_count: z.number().int().min(1).max(2550),
  persona_count: z.number().int().min(1).max(8),
  rounds: z.number().int().min(1).max(6),
  minutes_per_round: z.number().int().min(15).max(480),
  horizon_minutes: z.number().int().min(15).max(2880),
  scheduled_posts: z.array(scheduledPostSchema).min(1).max(6),
}).strict();

export const researchRunSchema = z.object({
  id: identifierSchema,
  research_project_id: identifierSchema,
  project_sha256: sha256DigestSchema,
  schema_version: z.enum([
    "sandowl-research-simulation-run/v1",
    "sandowl-research-simulation-run/v2",
    "sandowl-research-simulation-run/v3",
    "sandowl-research-simulation-run/v4",
  ]),
  cohort: cohortRefSchema,
  simulation_requirement: textSchema.max(4000),
  seed: z.number().int().min(0).max(2_147_483_647),
  rounds: z.number().int().min(1).max(6).nullable(),
  minutes_per_round: z.number().int().min(15).max(480).nullable(),
  initial_post: textSchema.max(4000).nullable(),
  engine: z.literal("camel-oasis"),
  engine_version: z.literal("0.2.5"),
  model_name: textSchema.max(200).nullable(),
  semantic_config_sha256: sha256DigestSchema.nullable(),
  prompt_schema_version: z.literal("matraix-semantic-profile/v1").nullable(),
  simulation_context: simulationContextSchema.nullable(),
  simulation_context_sha256: sha256DigestSchema.nullable(),
  simulation_plan: researchSimulationPlanSchema.nullable(),
  simulation_plan_sha256: sha256DigestSchema.nullable(),
  status: z.enum(["configured", "queued", "running", "succeeded", "failed"]),
  run_spec_sha256: sha256DigestSchema,
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  result: runResultSchema.nullable(),
  error: runErrorSchema.nullable(),
}).strict();

export const researchRunsResponseSchema = z.object({
  items: z.array(researchRunSchema),
  total: z.number().int().nonnegative(),
}).strict();

const scheduledPostRequestSchema = z.object({
  content: textSchema.max(4000),
  offset_minutes: z.number().int().min(15).max(2880),
}).strict();

export const researchRunCreateRequestSchema = z.object({
  cohort_id: identifierSchema,
  simulation_requirement: textSchema.max(4000),
  seed: z.number().int().min(0).max(2_147_483_647),
  planning_mode: z.enum(["manual", "automatic"]),
  rounds: z.number().int().min(1).max(6).nullable(),
  minutes_per_round: z.number().int().min(15).max(480).nullable(),
  time_horizon_minutes: z.number().int().min(60).max(2880).nullable(),
  activity_intensity: z.enum(["low", "standard", "high"]).nullable(),
  initial_post: textSchema.max(4000),
  scheduled_posts: z.array(scheduledPostRequestSchema).max(5),
}).strict().superRefine((request, context) => {
  const manual = request.planning_mode === "manual";
  if (manual !== (request.rounds !== null && request.minutes_per_round !== null)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["rounds"],
      message: "manual planning fields are incomplete",
    });
  }
  if (manual !== (
    request.time_horizon_minutes === null && request.activity_intensity === null
  )) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["time_horizon_minutes"],
      message: "automatic planning fields are invalid",
    });
  }
});

const researchRunEventSchema = z.object({
  sequence: z.number().int().positive(),
  round: z.number().int().min(1).max(6),
  phase: z.enum(["intervention", "audience"]),
  actor_kind: z.enum(["scenario", "persona"]),
  persona_id: identifierSchema.nullable(),
  agent_position: z.number().int().min(0).max(8),
  action_type: z.enum([
    "create_post", "create_comment", "like_post", "dislike_post", "do_nothing",
  ]),
  content: z.string().nullable(),
  post_id: z.string().nullable(),
  comment_id: z.string().nullable(),
  target_post_id: z.string().nullable(),
  observed_at_raw: z.string().min(1),
  recorded_at: timestampSchema,
}).strict();

const researchRunMemoryNodeSchema = z.object({
  position: z.number().int().min(0).max(127),
  key: textSchema.max(200),
  kind: z.enum(["scenario", "persona", "post", "comment"]),
  label: textSchema.max(500),
}).strict();

const researchRunMemoryEdgeSchema = z.object({
  position: z.number().int().min(0).max(127),
  sequence: z.number().int().positive(),
  source_key: textSchema.max(200),
  relation: z.enum(["authored", "commented_on", "liked", "disliked"]),
  target_key: textSchema.max(200),
}).strict();

const researchRunGraphMemorySchema = z.object({
  schema_version: z.literal("sandowl-run-graph-memory/v1"),
  run_spec_sha256: sha256DigestSchema,
  round: z.number().int().min(1).max(6),
  previous_sha256: sha256DigestSchema.nullable(),
  cumulative_event_count: z.number().int().min(1).max(54),
  nodes: z.array(researchRunMemoryNodeSchema).min(1).max(128),
  edges: z.array(researchRunMemoryEdgeSchema).max(128),
  memory_sha256: sha256DigestSchema,
  created_at: timestampSchema,
}).strict();

export const researchRunReportSchema = z.object({
  id: identifierSchema,
  research_project: researchProjectSchema,
  run: researchRunSchema,
  events: z.array(researchRunEventSchema),
  graph_memory: z.array(researchRunGraphMemorySchema).max(6),
  report_sha256: sha256DigestSchema,
  created_at: timestampSchema,
}).strict();

export const researchRunReportSummarySchema = researchRunReportSchema.omit({
  events: true,
  graph_memory: true,
});

export const researchRunReportsResponseSchema = z.object({
  items: z.array(researchRunReportSummarySchema),
  total: z.number().int().nonnegative(),
}).strict().refine((response) => response.total === response.items.length, {
  message: "Research report total must match items",
  path: ["total"],
});

export type ResearchRun = z.infer<typeof researchRunSchema>;
export type ResearchSimulationPlan = z.infer<typeof researchSimulationPlanSchema>;
export type ResearchRunsResponse = z.infer<typeof researchRunsResponseSchema>;
export type ResearchRunCreateRequest = z.infer<typeof researchRunCreateRequestSchema>;
export type ResearchRunReport = z.infer<typeof researchRunReportSchema>;
export type ResearchRunReportSummary = z.infer<typeof researchRunReportSummarySchema>;
export type ResearchRunReportsResponse = z.infer<typeof researchRunReportsResponseSchema>;

export function fetchResearchProjects(signal: AbortSignal): Promise<ResearchProjectsResponse> {
  return getJson(endpoint, researchProjectsResponseSchema, signal);
}

export function createResearchProject(
  request: ResearchProjectCreateRequest,
  signal: AbortSignal,
): Promise<ResearchProject> {
  return postJson(endpoint, request, researchProjectSchema, signal);
}

export function fetchResearchProjectAgendaContext(
  projectId: string,
  signal: AbortSignal,
): Promise<ResearchProjectAgendaContext | null> {
  return getJson(
    `${endpoint}/${projectId}/agenda-context`,
    researchProjectAgendaContextSchema.nullable(),
    signal,
  );
}

export function captureResearchProjectAgendaContext(
  projectId: string,
  signal: AbortSignal,
): Promise<ResearchProjectAgendaContext> {
  return postJson(
    `${endpoint}/${projectId}/agenda-context`,
    {},
    researchProjectAgendaContextSchema,
    signal,
  );
}

export function fetchResearchRuns(
  projectId: string,
  signal: AbortSignal,
): Promise<ResearchRunsResponse> {
  return getJson(`${endpoint}/${projectId}/runs`, researchRunsResponseSchema, signal);
}

export function createResearchRun(
  projectId: string,
  request: ResearchRunCreateRequest,
  signal: AbortSignal,
): Promise<ResearchRun> {
  return postJson(`${endpoint}/${projectId}/runs`, request, researchRunSchema, signal);
}

export function previewResearchRunPlan(
  projectId: string,
  request: ResearchRunCreateRequest,
  signal: AbortSignal,
): Promise<ResearchSimulationPlan> {
  return postJson(
    `${endpoint}/${projectId}/runs/plan-preview`,
    request,
    researchSimulationPlanSchema,
    signal,
  );
}

export function fetchResearchRunReport(
  projectId: string,
  runId: string,
  signal: AbortSignal,
): Promise<ResearchRunReport> {
  return getJson(
    `${endpoint}/${projectId}/runs/${runId}/report`,
    researchRunReportSchema,
    signal,
  );
}

export function fetchResearchRunReports(
  signal: AbortSignal,
): Promise<ResearchRunReportsResponse> {
  return getJson(`${endpoint}/reports`, researchRunReportsResponseSchema, signal);
}
