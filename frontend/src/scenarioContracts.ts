import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const scenariosEndpoint = "/api/v2/scenarios";
const identifierSchema = z.string().uuid();
const isoTimestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const singleLineTextSchema = nonEmptyTextSchema.regex(
  /^[^\r\n]+$/u,
  "Expected a single line of text",
);

const scenarioTitleSchema = singleLineTextSchema.max(300);
const variantNameSchema = singleLineTextSchema.max(200);
const decisionQuestionSchema = nonEmptyTextSchema.max(2_000);
const hypothesisSchema = nonEmptyTextSchema.max(2_000);
const interventionContentSchema = nonEmptyTextSchema.max(4_000);
const interventionOffsetSchema = z.number().int().min(0).max(1_440);

export const scenarioSnapshotSchema = z
  .object({
    world_model_id: identifierSchema,
    world_snapshot_id: identifierSchema,
    version: z.number().int().positive(),
    snapshot_sha256: sha256DigestSchema,
    evidence_count: z.number().int().min(1).max(50),
  })
  .strict();

export const scenarioSummarySchema = z
  .object({
    id: identifierSchema,
    title: scenarioTitleSchema,
    decision_question: decisionQuestionSchema,
    created_at: isoTimestampSchema,
    scenario_sha256: sha256DigestSchema,
    snapshot: scenarioSnapshotSchema,
  })
  .strict();

export const scenarioInterventionSchema = z
  .object({
    id: identifierSchema,
    position: z.number().int().nonnegative(),
    kind: z.literal("initial_post"),
    actor: z.literal("scenario_actor"),
    channel: z.literal("reddit"),
    content: interventionContentSchema,
    offset_minutes: interventionOffsetSchema,
  })
  .strict();

export const baselineVariantSchema = z
  .object({
    id: identifierSchema,
    position: z.literal(0),
    name: variantNameSchema,
    hypothesis: hypothesisSchema,
    interventions: z.tuple([]),
  })
  .strict();

export const alternativeVariantSchema = z
  .object({
    id: identifierSchema,
    position: z.number().int().positive(),
    name: variantNameSchema,
    hypothesis: hypothesisSchema,
    interventions: z.array(scenarioInterventionSchema).min(1).max(20),
  })
  .strict()
  .superRefine((variant, context) => {
    const positions = variant.interventions.map((intervention) => intervention.position);
    const ids = variant.interventions.map((intervention) => intervention.id);

    if (new Set(positions).size !== positions.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["interventions"],
        message: "intervention positions must be unique within a variant",
      });
    }

    const hasNonSequentialPosition = positions.some(
      (position, index) => position !== index,
    );

    if (hasNonSequentialPosition) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["interventions"],
        message: "intervention positions must be sequential from zero",
      });
    }

    if (new Set(ids).size !== ids.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["interventions"],
        message: "intervention identifiers must be unique within a variant",
      });
    }
  });

export const scenarioDetailSchema = scenarioSummarySchema
  .extend({
    baseline: baselineVariantSchema,
    alternatives: z.array(alternativeVariantSchema).min(1).max(5),
  })
  .strict()
  .superRefine((scenario, context) => {
    const variants = [scenario.baseline, ...scenario.alternatives];
    const variantIds = variants.map((variant) => variant.id);
    const alternativePositions = scenario.alternatives.map((variant) => variant.position);
    const interventionIds = scenario.alternatives.flatMap((variant) =>
      variant.interventions.map((intervention) => intervention.id),
    );

    if (new Set(variantIds).size !== variantIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["alternatives"],
        message: "variant identifiers must be unique",
      });
    }

    if (new Set(alternativePositions).size !== alternativePositions.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["alternatives"],
        message: "alternative positions must be unique",
      });
    }

    const hasNonSequentialAlternativePosition = alternativePositions.some(
      (position, index) => position !== index + 1,
    );

    if (hasNonSequentialAlternativePosition) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["alternatives"],
        message: "alternative positions must be sequential from one",
      });
    }

    if (new Set(interventionIds).size !== interventionIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["alternatives"],
        message: "intervention identifiers must be unique across the scenario",
      });
    }
  });

export const scenariosResponseSchema = z
  .object({
    items: z.array(scenarioSummarySchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const scenarioInterventionRequestSchema = z
  .object({
    kind: z.literal("initial_post"),
    actor: z.literal("scenario_actor"),
    channel: z.literal("reddit"),
    content: interventionContentSchema,
    offset_minutes: interventionOffsetSchema,
  })
  .strict();

export const scenarioVariantRequestSchema = z
  .object({
    name: variantNameSchema,
    hypothesis: hypothesisSchema,
    interventions: z.array(scenarioInterventionRequestSchema).min(1).max(20),
  })
  .strict();

export const scenarioCreateRequestSchema = z
  .object({
    title: scenarioTitleSchema,
    decision_question: decisionQuestionSchema,
    world_model_id: identifierSchema,
    world_snapshot_id: identifierSchema,
    baseline: z
      .object({
        name: variantNameSchema,
        hypothesis: hypothesisSchema,
      })
      .strict(),
    alternatives: z.array(scenarioVariantRequestSchema).min(1).max(5),
  })
  .strict();

export type ScenarioSnapshot = z.infer<typeof scenarioSnapshotSchema>;
export type ScenarioSummary = z.infer<typeof scenarioSummarySchema>;
export type ScenarioIntervention = z.infer<typeof scenarioInterventionSchema>;
export type BaselineVariant = z.infer<typeof baselineVariantSchema>;
export type AlternativeVariant = z.infer<typeof alternativeVariantSchema>;
export type ScenarioDetail = z.infer<typeof scenarioDetailSchema>;
export type ScenariosResponse = z.infer<typeof scenariosResponseSchema>;
export type ScenarioInterventionRequest = z.infer<typeof scenarioInterventionRequestSchema>;
export type ScenarioVariantRequest = z.infer<typeof scenarioVariantRequestSchema>;
export type ScenarioCreateRequest = z.infer<typeof scenarioCreateRequestSchema>;

export function createScenarioDetailEndpoint(scenarioId: string): string {
  return `${scenariosEndpoint}/${encodeURIComponent(scenarioId)}`;
}

export function fetchScenarios(signal: AbortSignal): Promise<ScenariosResponse> {
  return getJson(scenariosEndpoint, scenariosResponseSchema, signal);
}

export function fetchScenarioDetail(
  scenarioId: string,
  signal: AbortSignal,
): Promise<ScenarioDetail> {
  return getJson(
    createScenarioDetailEndpoint(scenarioId),
    scenarioDetailSchema,
    signal,
  );
}

export function createScenario(
  request: ScenarioCreateRequest,
  signal: AbortSignal,
): Promise<ScenarioDetail> {
  const validatedRequest = scenarioCreateRequestSchema.parse(request);

  return postJson(scenariosEndpoint, validatedRequest, scenarioDetailSchema, signal);
}
