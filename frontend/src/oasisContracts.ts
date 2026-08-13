import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const platformSmokeRunsEndpoint = "/api/v2/simulation-runs/platform-smoke";
const oasisReadinessEndpoint = "/api/v2/simulations/oasis/readiness";
const identifierSchema = z.string().uuid();
const isoTimestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const singleLineTextSchema = nonEmptyTextSchema.regex(
  /^[^\r\n]+$/u,
  "Expected a single line of text",
);
const identifierTextSchema = z
  .string()
  .trim()
  .min(1)
  .max(128)
  .regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u);
const nullableTimestampSchema = isoTimestampSchema.nullable();
const runStatusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const seedSchema = z.number().int().min(0).max(4_294_967_295);

export const oasisReadinessSchema = z
  .object({
    engine: z.literal("camel-oasis"),
    engine_version: z.literal("0.2.5"),
    mode: z.literal("reddit_manual_smoke"),
    worker_online: z.boolean(),
    platform_runtime_ready: z.boolean(),
    semantic_run_ready: z.literal(false),
    limitations: z.array(nonEmptyTextSchema),
  })
  .strict();

export const platformSmokeScenarioSchema = z
  .object({
    id: identifierSchema,
    scenario_sha256: sha256DigestSchema,
    variant_id: identifierSchema,
    variant_name: singleLineTextSchema.max(200),
    world_snapshot_id: identifierSchema,
    snapshot_sha256: sha256DigestSchema,
  })
  .strict();

export const platformSmokePostSchema = z
  .object({
    position: z.number().int().min(0).max(19),
    content: nonEmptyTextSchema.max(4_000),
    offset_minutes: z.number().int().min(0).max(1_440),
  })
  .strict();

export const platformSmokeResultSchema = z
  .object({
    engine_version: z.literal("0.2.5"),
    camel_version: z.literal("0.2.78"),
    artifact_sha256: sha256DigestSchema,
    artifact_size_bytes: z.number().int().positive(),
    user_count: z.literal(1),
    post_count: z.number().int().min(1).max(20),
    trace_count: z.number().int().min(2).max(21),
    limitations: z.array(nonEmptyTextSchema),
  })
  .strict()
  .superRefine((result, context) => {
    if (result.trace_count !== result.post_count + 1) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["trace_count"],
        message: "trace_count must equal post_count + 1",
      });
    }
  });

export const platformSmokeErrorSchema = z
  .object({
    code: identifierTextSchema,
    message: nonEmptyTextSchema,
  })
  .strict();

const platformSmokeRunBaseSchema = z
  .object({
    id: identifierSchema,
    mode: z.literal("reddit_manual_smoke"),
    status: runStatusSchema,
    created_at: isoTimestampSchema,
    started_at: nullableTimestampSchema,
    completed_at: nullableTimestampSchema,
    scenario: platformSmokeScenarioSchema,
    seed: seedSchema,
    input_sha256: sha256DigestSchema,
  })
  .strict();

export const platformSmokeRunSummarySchema = platformSmokeRunBaseSchema;

export const platformSmokeRunDetailSchema = platformSmokeRunBaseSchema
  .extend({
    posts: z.array(platformSmokePostSchema).min(1).max(20),
    result: platformSmokeResultSchema.nullable(),
    error: platformSmokeErrorSchema.nullable(),
  })
  .strict()
  .superRefine((run, context) => {
    const positions = run.posts.map((post) => post.position);
    const hasNonSequentialPosition = positions.some(
      (position, index) => position !== index,
    );

    if (hasNonSequentialPosition) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["posts"],
        message: "post positions must be sequential from zero",
      });
    }

    if (run.status === "queued") {
      if (
        run.started_at !== null
        || run.completed_at !== null
        || run.result !== null
        || run.error !== null
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "queued runs cannot have execution timestamps or terminal output",
        });
      }
    } else if (run.status === "running") {
      if (
        run.started_at === null
        || run.completed_at !== null
        || run.result !== null
        || run.error !== null
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "running runs require only started_at",
        });
      }
    } else if (run.status === "succeeded") {
      if (
        run.started_at === null
        || run.completed_at === null
        || run.result === null
        || run.error !== null
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "succeeded runs require timestamps and only a result",
        });
      }
    } else if (
      run.started_at === null
      || run.completed_at === null
      || run.result !== null
      || run.error === null
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "failed runs require timestamps and only an error",
      });
    }
  });

export const platformSmokeRunsResponseSchema = z
  .object({
    items: z.array(platformSmokeRunSummarySchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const createPlatformSmokeRunRequestSchema = z
  .object({
    scenario_id: identifierSchema,
    variant_id: identifierSchema,
    seed: seedSchema,
  })
  .strict();

export type OasisReadiness = z.infer<typeof oasisReadinessSchema>;
export type PlatformSmokeRunSummary = z.infer<typeof platformSmokeRunSummarySchema>;
export type PlatformSmokeRunDetail = z.infer<typeof platformSmokeRunDetailSchema>;
export type PlatformSmokeRunsResponse = z.infer<typeof platformSmokeRunsResponseSchema>;
export type CreatePlatformSmokeRunRequest = z.infer<
  typeof createPlatformSmokeRunRequestSchema
>;

export function createPlatformSmokeRunDetailEndpoint(runId: string): string {
  return `${platformSmokeRunsEndpoint}/${encodeURIComponent(runId)}`;
}

export function fetchOasisReadiness(signal: AbortSignal): Promise<OasisReadiness> {
  return getJson(oasisReadinessEndpoint, oasisReadinessSchema, signal);
}

export function fetchPlatformSmokeRuns(
  signal: AbortSignal,
): Promise<PlatformSmokeRunsResponse> {
  return getJson(
    platformSmokeRunsEndpoint,
    platformSmokeRunsResponseSchema,
    signal,
  );
}

export function fetchPlatformSmokeRunDetail(
  runId: string,
  signal: AbortSignal,
): Promise<PlatformSmokeRunDetail> {
  return getJson(
    createPlatformSmokeRunDetailEndpoint(runId),
    platformSmokeRunDetailSchema,
    signal,
  );
}

export function createPlatformSmokeRun(
  request: CreatePlatformSmokeRunRequest,
  signal: AbortSignal,
): Promise<PlatformSmokeRunDetail> {
  const validatedRequest = createPlatformSmokeRunRequestSchema.parse(request);

  return postJson(
    platformSmokeRunsEndpoint,
    validatedRequest,
    platformSmokeRunDetailSchema,
    signal,
  );
}
