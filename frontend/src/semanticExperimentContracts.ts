import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const semanticExperimentsEndpoint = "/api/v2/semantic-experiments";
const semanticTrialsEndpoint = "/api/v2/semantic-trials";
const semanticReadinessEndpoint = "/api/v2/simulations/oasis/semantic-readiness";
const identifierSchema = z.string().uuid();
const isoTimestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const singleLineTextSchema = nonEmptyTextSchema.regex(
  /^[^\r\n]+$/u,
  "Expected a single line of text",
);
const nullableTimestampSchema = isoTimestampSchema.nullable();
const uint32Schema = z.number().int().min(0).max(4_294_967_295);
const runStatusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const modelNameSchema = singleLineTextSchema.max(200);
const promptSchemaVersionSchema = z.literal("matraix-semantic-profile/v1");
const boundedCountSchema = z.number().int().nonnegative();

export const semanticExperimentCreateRequestSchema = z
  .object({
    scenario_id: identifierSchema,
    cohort_id: identifierSchema,
    alternative_ids: z.array(identifierSchema).min(1).max(2),
    seeds: z.array(uint32Schema).min(1).max(2),
    rounds: z.number().int().min(1).max(3),
    minutes_per_round: z.number().int().min(15).max(240),
  })
  .strict()
  .superRefine((request, context) => {
    if (new Set(request.alternative_ids).size !== request.alternative_ids.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["alternative_ids"],
        message: "alternative identifiers must be unique",
      });
    }

    if (new Set(request.seeds).size !== request.seeds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["seeds"],
        message: "seeds must be unique",
      });
    }
  });

export const semanticReadinessSchema = z
  .object({
    engine: z.literal("camel-oasis"),
    engine_version: z.literal("0.2.5"),
    camel_version: z.literal("0.2.78"),
    worker_online: z.boolean(),
    live_worker_count: z.number().int().nonnegative(),
    semantic_runtime_ready: z.boolean(),
    configuration_conflict: z.boolean(),
    model_name: modelNameSchema.nullable(),
    semantic_config_sha256: sha256DigestSchema.nullable(),
    prompt_schema_version: promptSchemaVersionSchema.nullable(),
    limitations: z.array(nonEmptyTextSchema).min(1),
  })
  .strict()
  .superRefine((readiness, context) => {
    if (readiness.worker_online !== (readiness.live_worker_count > 0)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["live_worker_count"],
        message: "worker_online must match live_worker_count",
      });
    }

    const hasCompleteConfiguration = readiness.model_name !== null
      && readiness.semantic_config_sha256 !== null
      && readiness.prompt_schema_version !== null;
    const hasAnyConfiguration = readiness.model_name !== null
      || readiness.semantic_config_sha256 !== null
      || readiness.prompt_schema_version !== null;

    if (hasAnyConfiguration !== hasCompleteConfiguration) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "semantic configuration fields must be all present or all absent",
      });
    }

    if (readiness.semantic_runtime_ready
      !== (readiness.worker_online && !readiness.configuration_conflict && hasCompleteConfiguration)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "semantic readiness must exactly match worker and configuration state",
      });
    }

    if (!readiness.semantic_runtime_ready && hasCompleteConfiguration) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "an unready runtime cannot expose selected model provenance",
      });
    }
  });

export const semanticScenarioSchema = z
  .object({
    id: identifierSchema,
    title: singleLineTextSchema.max(300),
    decision_question: nonEmptyTextSchema.max(2_000),
    scenario_sha256: sha256DigestSchema,
  })
  .strict();

export const semanticCohortSchema = z
  .object({
    id: identifierSchema,
    title: singleLineTextSchema.max(200),
    cohort_sha256: sha256DigestSchema,
    dataset_sha256: sha256DigestSchema,
    persona_count: z.number().int().min(1).max(8),
  })
  .strict();

const semanticExperimentSummaryBaseSchema = z
  .object({
    id: identifierSchema,
    status: runStatusSchema,
    created_at: isoTimestampSchema,
    scenario: semanticScenarioSchema,
    cohort: semanticCohortSchema,
    variant_count: z.number().int().min(2).max(3),
    trial_count: z.number().int().min(2).max(6),
    rounds: z.number().int().min(1).max(3),
    minutes_per_round: z.number().int().min(15).max(240),
    seeds: z.array(uint32Schema).min(1).max(2),
    model_name: modelNameSchema,
    semantic_config_sha256: sha256DigestSchema,
    prompt_schema_version: promptSchemaVersionSchema,
    experiment_sha256: sha256DigestSchema,
  })
  .strict();

export const semanticExperimentSummarySchema = semanticExperimentSummaryBaseSchema
  .superRefine((experiment, context) => {
    if (new Set(experiment.seeds).size !== experiment.seeds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["seeds"],
        message: "seeds must be unique",
      });
    }

    if (experiment.seeds.some((seed, index) => {
      const previousSeed = experiment.seeds[index - 1];
      return previousSeed !== undefined && seed <= previousSeed;
    })) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["seeds"],
        message: "seeds must be ordered ascending",
      });
    }

    if (experiment.trial_count !== experiment.variant_count * experiment.seeds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["trial_count"],
        message: "trial_count must equal variant_count times seed count",
      });
    }
  });

export const semanticTrialResultSchema = z
  .object({
    engine_version: z.literal("0.2.5"),
    camel_version: z.literal("0.2.78"),
    model_name: modelNameSchema,
    semantic_config_sha256: sha256DigestSchema,
    prompt_schema_version: promptSchemaVersionSchema,
    artifact_sha256: sha256DigestSchema,
    artifact_size_bytes: z.number().int().positive(),
    user_count: z.number().int().min(2).max(9),
    initial_post_count: boundedCountSchema,
    generated_post_count: boundedCountSchema,
    comment_count: boundedCountSchema,
    reaction_count: boundedCountSchema,
    do_nothing_count: boundedCountSchema,
    observed_action_count: boundedCountSchema,
    authored_content_count: boundedCountSchema,
    rounds_completed: z.number().int().min(1).max(3),
    limitations: z.array(nonEmptyTextSchema).min(1),
  })
  .strict()
  .superRefine((result, context) => {
    if (result.authored_content_count !== result.generated_post_count + result.comment_count) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["authored_content_count"],
        message: "authored_content_count must equal generated posts plus comments",
      });
    }

    if (result.observed_action_count
      !== result.initial_post_count
        + result.generated_post_count
        + result.comment_count
        + result.reaction_count
        + result.do_nothing_count) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["observed_action_count"],
        message: "observed_action_count must equal all normalized action counts",
      });
    }
  });

export const semanticTrialErrorSchema = z
  .object({
    code: singleLineTextSchema.max(128),
    message: nonEmptyTextSchema.max(4_000),
  })
  .strict();

export const semanticTrialSchema = z
  .object({
    id: identifierSchema,
    status: runStatusSchema,
    seed: uint32Schema,
    trial_sha256: sha256DigestSchema,
    current_round: z.number().int().min(0).max(3),
    created_at: isoTimestampSchema,
    started_at: nullableTimestampSchema,
    completed_at: nullableTimestampSchema,
    result: semanticTrialResultSchema.nullable(),
    error: semanticTrialErrorSchema.nullable(),
  })
  .strict()
  .superRefine((trial, context) => {
    if (trial.status === "queued"
      && (trial.started_at !== null || trial.completed_at !== null
        || trial.result !== null || trial.error !== null || trial.current_round !== 0)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "queued trial has execution output" });
    }

    if (trial.status === "running"
      && (trial.started_at === null || trial.completed_at !== null
        || trial.result !== null || trial.error !== null)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "running trial lifecycle is invalid" });
    }

    if (trial.status === "succeeded"
      && (trial.started_at === null || trial.completed_at === null
        || trial.result === null || trial.error !== null)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "succeeded trial requires only result" });
    }

    if (trial.status === "failed"
      && (trial.started_at === null || trial.completed_at === null
        || trial.result !== null || trial.error === null)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "failed trial requires only error" });
    }
  });

export const semanticVariantSchema = z
  .object({
    position: z.number().int().min(0).max(2),
    role: z.enum(["baseline", "alternative"]),
    id: identifierSchema,
    scenario_position: z.number().int().min(0).max(5),
    name: singleLineTextSchema.max(200),
    hypothesis: nonEmptyTextSchema.max(2_000),
    intervention_count: z.number().int().min(0).max(20),
    trials: z.array(semanticTrialSchema).min(1).max(2),
  })
  .strict()
  .superRefine((variant, context) => {
    if (variant.position === 0
      && (variant.role !== "baseline" || variant.scenario_position !== 0)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "baseline must occupy Scenario position zero" });
    }

    if (variant.position > 0
      && (variant.role !== "alternative" || variant.scenario_position < 1)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "alternative must reference a nonzero Scenario position" });
    }

    if (variant.role === "baseline" && variant.intervention_count !== 0) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["intervention_count"], message: "baseline cannot have interventions" });
    }

    if (variant.role === "alternative" && variant.intervention_count < 1) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["intervention_count"], message: "alternative requires at least one intervention" });
    }

    if (variant.trials.some((trial, index) => {
      const previousTrial = variant.trials[index - 1];
      return previousTrial !== undefined && trial.seed <= previousTrial.seed;
    })) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["trials"], message: "trials must be ordered by seed" });
    }
  });

export const semanticExperimentDetailSchema = semanticExperimentSummaryBaseSchema
  .extend({
    variants: z.array(semanticVariantSchema).min(2).max(3),
  })
  .strict()
  .superRefine((experiment, context) => {
    if (new Set(experiment.seeds).size !== experiment.seeds.length
      || experiment.seeds.some((seed, index) => {
        const previousSeed = experiment.seeds[index - 1];
        return previousSeed !== undefined && seed <= previousSeed;
      })) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["seeds"], message: "seeds must be unique and ordered ascending" });
    }

    if (experiment.trial_count !== experiment.variant_count * experiment.seeds.length) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["trial_count"], message: "trial_count must equal the matrix dimensions" });
    }

    if (experiment.variants.length !== experiment.variant_count) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["variants"], message: "variant count mismatch" });
    }

    if (experiment.variants.some((variant, index) => variant.position !== index)) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["variants"], message: "variants must be contiguous from baseline position zero" });
    }

    for (const [variantIndex, variant] of experiment.variants.entries()) {
      if (variant.trials.length !== experiment.seeds.length
        || variant.trials.some((trial, index) => trial.seed !== experiment.seeds[index])) {
        context.addIssue({ code: z.ZodIssueCode.custom, path: ["variants", variantIndex, "trials"], message: "every variant must contain the experiment seed matrix" });
      }

      if (variant.trials.some((trial) => trial.current_round > experiment.rounds)) {
        context.addIssue({ code: z.ZodIssueCode.custom, path: ["variants", variantIndex, "trials"], message: "current_round exceeds experiment rounds" });
      }


      for (const [trialIndex, trial] of variant.trials.entries()) {
        if (trial.result !== null
          && (
            trial.result.user_count !== experiment.cohort.persona_count + 1
            || trial.result.rounds_completed !== experiment.rounds
            || trial.result.model_name !== experiment.model_name
            || trial.result.semantic_config_sha256 !== experiment.semantic_config_sha256
            || trial.result.prompt_schema_version !== experiment.prompt_schema_version
          )) {
          context.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["variants", variantIndex, "trials", trialIndex, "result"],
            message: "trial result provenance or dimensions do not match the experiment",
          });
        }
      }
    }
  });

export const semanticExperimentsResponseSchema = z
  .object({
    items: z.array(semanticExperimentSummarySchema),
    total: z.number().int().nonnegative(),
  })
  .strict()
  .superRefine((response, context) => {
    const outOfOrder = response.items.some((item, index) => {
      const previous = response.items[index - 1];
      if (previous === undefined) {
        return false;
      }

      const itemTime = Date.parse(item.created_at);
      const previousTime = Date.parse(previous.created_at);
      return itemTime > previousTime
        || (itemTime === previousTime && item.id < previous.id);
    });

    if (outOfOrder) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["items"], message: "experiments must be ordered by created_at desc and id asc" });
    }
  });

const eventIdSchema = singleLineTextSchema.max(128).nullable();

export const semanticTrialEventSchema = z
  .object({
    sequence: z.number().int().positive(),
    round: z.number().int().min(1).max(3),
    phase: z.enum(["intervention", "audience"]),
    actor_kind: z.enum(["scenario", "persona"]),
    persona_id: identifierSchema.nullable(),
    agent_position: z.number().int().min(0).max(8),
    action_type: z.enum([
      "create_post",
      "create_comment",
      "like_post",
      "dislike_post",
      "do_nothing",
    ]),
    content: nonEmptyTextSchema.max(4_000).nullable(),
    post_id: eventIdSchema,
    comment_id: eventIdSchema,
    target_post_id: eventIdSchema,
    observed_at_raw: singleLineTextSchema.max(200),
    recorded_at: isoTimestampSchema,
  })
  .strict()
  .superRefine((event, context) => {
    if ((event.actor_kind === "persona") !== (event.persona_id !== null)) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["persona_id"], message: "persona identity must match actor kind" });
    }


    if (event.actor_kind === "scenario" && event.agent_position !== 0) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["agent_position"], message: "scenario actor requires position zero" });
    }

    if (event.actor_kind === "persona" && event.agent_position < 1) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["agent_position"], message: "persona actor requires a positive position" });
    }


    if (event.phase === "intervention"
      && (event.actor_kind !== "scenario" || event.action_type !== "create_post")) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "intervention events must be scenario posts" });
    }

    if (event.phase === "audience" && event.actor_kind !== "persona") {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "audience events require a persona actor" });
    }

    const hasContent = event.content !== null;
    const hasPostId = event.post_id !== null;
    const hasCommentId = event.comment_id !== null;
    const hasTargetPostId = event.target_post_id !== null;

    if (event.action_type === "create_post"
      && (!hasContent || !hasPostId || hasCommentId || hasTargetPostId)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "create_post action fields are invalid" });
    } else if (event.action_type === "create_comment"
      && (!hasContent || hasPostId || !hasCommentId || !hasTargetPostId)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "create_comment action fields are invalid" });
    } else if ((event.action_type === "like_post" || event.action_type === "dislike_post")
      && (hasContent || hasPostId || hasCommentId || !hasTargetPostId)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "reaction action fields are invalid" });
    } else if (event.action_type === "do_nothing"
      && (hasContent || hasPostId || hasCommentId || hasTargetPostId)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "do_nothing cannot carry content or object identifiers" });
    }
  });

export const semanticTrialEventsPageSchema = z
  .object({
    trial_id: identifierSchema,
    after_sequence: z.number().int().nonnegative(),
    next_after_sequence: z.number().int().nonnegative(),
    has_more: z.boolean(),
    items: z.array(semanticTrialEventSchema).max(100),
  })
  .strict()
  .superRefine((page, context) => {
    if (page.items.some((event, index) => event.sequence !== page.after_sequence + index + 1)) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["items"], message: "event sequence must be contiguous after cursor" });
    }

    const expectedCursor = page.items.at(-1)?.sequence ?? page.after_sequence;
    if (page.next_after_sequence !== expectedCursor) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["next_after_sequence"], message: "next cursor must equal final sequence" });
    }
  });

const comparisonMetricSchema = z.enum([
  "observed_action_count",
  "authored_content_count",
  "reaction_count",
  "do_nothing_count",
]);
const comparisonMetricOrder = [
  "observed_action_count",
  "authored_content_count",
  "reaction_count",
  "do_nothing_count",
] as const;

export const semanticComparisonVariantSchema = z
  .object({
    position: z.number().int().min(0).max(2),
    role: z.enum(["baseline", "alternative"]),
    id: identifierSchema,
    name: singleLineTextSchema.max(200),
    n: z.number().int().min(1).max(2),
    mean: z.number().finite(),
    stddev: z.number().finite().nonnegative(),
  })
  .strict();

export const semanticPairedDeltaSchema = z
  .object({
    alternative_position: z.number().int().min(1).max(2),
    alternative_id: identifierSchema,
    alternative_name: singleLineTextSchema.max(200),
    n: z.number().int().min(1).max(2),
    mean_delta: z.number().finite(),
    stddev_delta: z.number().finite().nonnegative(),
  })
  .strict();

export const semanticComparisonMetricSchema = z
  .object({
    metric: comparisonMetricSchema,
    variants: z.array(semanticComparisonVariantSchema).max(3),
    paired_deltas: z.array(semanticPairedDeltaSchema).max(2),
  })
  .strict()
  .superRefine((metric, context) => {
    const variantsById = new Map(metric.variants.map((variant) => [variant.id, variant]));
    if (new Set(metric.variants.map((variant) => variant.id)).size !== metric.variants.length) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["variants"], message: "comparison variants must be unique" });
    }

    if (metric.variants.filter((variant) => variant.role === "baseline").length > 1) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["variants"], message: "comparison cannot contain multiple baselines" });
    }

    for (const [index, delta] of metric.paired_deltas.entries()) {
      const variant = variantsById.get(delta.alternative_id);
      if (variant === undefined
        || variant.role !== "alternative"
        || variant.position !== delta.alternative_position
        || variant.name !== delta.alternative_name) {
        context.addIssue({ code: z.ZodIssueCode.custom, path: ["paired_deltas", index], message: "paired delta must reference an emitted alternative observation" });
      }
    }
  });

export const semanticExperimentComparisonSchema = z
  .object({
    experiment_id: identifierSchema,
    complete: z.boolean(),
    state: z.enum(["pending", "partial", "complete", "failed"]),
    metrics: z.array(semanticComparisonMetricSchema).length(4),
    limitations: z.array(nonEmptyTextSchema).min(1),
  })
  .strict()
  .superRefine((comparison, context) => {
    const metricNames = comparison.metrics.map((metric) => metric.metric);
    if (new Set(metricNames).size !== metricNames.length) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["metrics"], message: "comparison metrics must be unique" });
    }

    if (comparison.complete !== (comparison.state === "complete")) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["complete"], message: "complete flag must match state" });
    }

    if (metricNames.some((metric, index) => metric !== comparisonMetricOrder[index])) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ["metrics"], message: "comparison metrics must use the fixed contract order" });
    }

    if (comparison.state === "complete") {
      const referenceVariants = comparison.metrics[0]?.variants ?? [];
      const referenceIds = referenceVariants.map((variant) => variant.id);
      const hasCompleteReference = referenceVariants.length >= 2
        && referenceVariants[0]?.role === "baseline"
        && referenceVariants[0]?.position === 0
        && referenceVariants.slice(1).every(
          (variant, index) => variant.role === "alternative" && variant.position === index + 1,
        );
      const everyMetricIsComplete = comparison.metrics.every((metric) =>
        metric.variants.map((variant) => variant.id).join(":") === referenceIds.join(":")
        && metric.paired_deltas.length === referenceVariants.length - 1,
      );

      if (!hasCompleteReference || !everyMetricIsComplete) {
        context.addIssue({ code: z.ZodIssueCode.custom, path: ["metrics"], message: "complete comparison requires every variant and paired delta in every metric" });
      }
    }
  });

export type SemanticExperimentCreateRequest = z.infer<typeof semanticExperimentCreateRequestSchema>;
export type SemanticReadiness = z.infer<typeof semanticReadinessSchema>;
export type SemanticExperimentSummary = z.infer<typeof semanticExperimentSummarySchema>;
export type SemanticTrialResult = z.infer<typeof semanticTrialResultSchema>;
export type SemanticTrial = z.infer<typeof semanticTrialSchema>;
export type SemanticVariant = z.infer<typeof semanticVariantSchema>;
export type SemanticExperimentDetail = z.infer<typeof semanticExperimentDetailSchema>;
export type SemanticExperimentsResponse = z.infer<typeof semanticExperimentsResponseSchema>;
export type SemanticTrialEvent = z.infer<typeof semanticTrialEventSchema>;
export type SemanticTrialEventsPage = z.infer<typeof semanticTrialEventsPageSchema>;
export type SemanticExperimentComparison = z.infer<typeof semanticExperimentComparisonSchema>;

export function createSemanticExperimentDetailEndpoint(experimentId: string): string {
  return `${semanticExperimentsEndpoint}/${encodeURIComponent(identifierSchema.parse(experimentId))}`;
}

export function createSemanticExperimentComparisonEndpoint(experimentId: string): string {
  return `${createSemanticExperimentDetailEndpoint(experimentId)}/comparison`;
}

export function createSemanticTrialEventsEndpoint(
  trialId: string,
  afterSequence: number,
): string {
  const parameters = new URLSearchParams({
    after_sequence: String(z.number().int().nonnegative().parse(afterSequence)),
    limit: "100",
  });

  return `${semanticTrialsEndpoint}/${encodeURIComponent(identifierSchema.parse(trialId))}/events?${parameters.toString()}`;
}

export function fetchSemanticReadiness(signal: AbortSignal): Promise<SemanticReadiness> {
  return getJson(semanticReadinessEndpoint, semanticReadinessSchema, signal);
}

export function fetchSemanticExperiments(signal: AbortSignal): Promise<SemanticExperimentsResponse> {
  return getJson(semanticExperimentsEndpoint, semanticExperimentsResponseSchema, signal);
}

export function fetchSemanticExperimentDetail(
  experimentId: string,
  signal: AbortSignal,
): Promise<SemanticExperimentDetail> {
  return getJson(
    createSemanticExperimentDetailEndpoint(experimentId),
    semanticExperimentDetailSchema,
    signal,
  );
}

export function fetchSemanticExperimentComparison(
  experimentId: string,
  signal: AbortSignal,
): Promise<SemanticExperimentComparison> {
  return getJson(
    createSemanticExperimentComparisonEndpoint(experimentId),
    semanticExperimentComparisonSchema,
    signal,
  );
}

export function fetchSemanticTrialEvents(
  trialId: string,
  afterSequence: number,
  signal: AbortSignal,
): Promise<SemanticTrialEventsPage> {
  return getJson(
    createSemanticTrialEventsEndpoint(trialId, afterSequence),
    semanticTrialEventsPageSchema,
    signal,
  );
}

export function createSemanticExperiment(
  request: SemanticExperimentCreateRequest,
  signal: AbortSignal,
): Promise<SemanticExperimentDetail> {
  return postJson(
    semanticExperimentsEndpoint,
    semanticExperimentCreateRequestSchema.parse(request),
    semanticExperimentDetailSchema,
    signal,
  );
}
