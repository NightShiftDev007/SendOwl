import { z } from "zod";

import { getJson } from "./apiClient";

const isoTimestampSchema = z.string().datetime({ offset: true });
const nullableTimestampSchema = isoTimestampSchema.nullable();
const identifierSchema = z
  .string()
  .trim()
  .min(1)
  .max(128)
  .regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u);
const nonEmptyTextSchema = z.string().trim().min(1);

export const mediaSyncTableNames = [
  "sources",
  "articles",
  "topics",
  "topic_articles",
  "topic_snapshots",
  "propagation_events",
  "propagation_edges",
  "first_utterances",
] as const;

const mediaSyncTriggerSchema = z.enum(["manual", "scheduled"]);
const mediaSyncRunStatusSchema = z.enum([
  "running",
  "succeeded",
  "failed",
  "skipped_concurrent",
]);
const mediaSyncTableNameSchema = z.enum(mediaSyncTableNames);

export const mediaSyncWatermarksSchema = z
  .object({
    latest_source_updated_at: nullableTimestampSchema,
    latest_article_crawled_at: nullableTimestampSchema,
    latest_topic_updated_at: nullableTimestampSchema,
    latest_topic_article_assigned_at: nullableTimestampSchema,
    latest_snapshot_created_at: nullableTimestampSchema,
    latest_snapshot_window_end: nullableTimestampSchema,
    latest_propagation_updated_at: nullableTimestampSchema,
  })
  .strict();

export const mediaArticleReconciliationSchema = z.object({
  present_count: z.number().int().nonnegative(),
  absent_count: z.number().int().nonnegative(),
  latest_absent_at: nullableTimestampSchema,
}).strict().superRefine((value, context) => {
  if ((value.absent_count === 0) !== (value.latest_absent_at === null)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["latest_absent_at"],
      message: "latest_absent_at must match absent_count",
    });
  }
});

export const mediaSyncTableCountSchema = z
  .object({
    table_name: mediaSyncTableNameSchema,
    read_count: z.number().int().nonnegative(),
    inserted_count: z.number().int().nonnegative(),
    updated_count: z.number().int().nonnegative(),
    skipped_count: z.number().int().nonnegative(),
  })
  .strict()
  .superRefine((count, context) => {
    if (
      count.read_count
      !== count.inserted_count + count.updated_count + count.skipped_count
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["read_count"],
        message: "read_count must equal inserted_count + updated_count + skipped_count",
      });
    }
  });

const mediaSyncRunErrorSchema = z
  .object({
    code: z
      .string()
      .min(1)
      .max(128)
      .regex(/^[a-z][a-z0-9_]{0,127}$/u),
    message: nonEmptyTextSchema.max(500),
  })
  .strict();

function hasCompleteTableAccounting(
  tableCounts: readonly z.infer<typeof mediaSyncTableCountSchema>[],
): boolean {
  const names = new Set(tableCounts.map((count) => count.table_name));

  return tableCounts.length === mediaSyncTableNames.length
    && names.size === mediaSyncTableNames.length
    && mediaSyncTableNames.every((name) => names.has(name));
}

export const mediaSyncRunSchema = z
  .object({
    id: z.string().uuid(),
    trigger: mediaSyncTriggerSchema,
    status: mediaSyncRunStatusSchema,
    worker_id: identifierSchema,
    started_at: isoTimestampSchema,
    completed_at: nullableTimestampSchema,
    next_scheduled_at: nullableTimestampSchema,
    source_observed_at: nullableTimestampSchema,
    source_watermarks: mediaSyncWatermarksSchema.nullable(),
    table_counts: z.array(mediaSyncTableCountSchema),
    error: mediaSyncRunErrorSchema.nullable(),
  })
  .strict()
  .superRefine((run, context) => {
    const publishesNextSchedule = run.trigger === "scheduled"
      && (run.status === "succeeded" || run.status === "skipped_concurrent");
    if ((run.next_scheduled_at !== null) !== publishesNextSchedule) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["next_scheduled_at"],
        message: "only successful or concurrently skipped scheduled syncs publish a next timestamp",
      });
    }

    if (
      run.completed_at !== null
      && Date.parse(run.completed_at) < Date.parse(run.started_at)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["completed_at"],
        message: "media sync completion cannot precede its start",
      });
    }

    const isRunningValid = run.completed_at === null
      && run.source_observed_at === null
      && run.source_watermarks === null
      && run.table_counts.length === 0
      && run.error === null;
    const isSucceededValid = run.completed_at !== null
      && run.source_observed_at !== null
      && run.source_watermarks !== null
      && hasCompleteTableAccounting(run.table_counts)
      && run.error === null;
    const isFailedValid = run.completed_at !== null
      && run.source_observed_at === null
      && run.source_watermarks === null
      && run.table_counts.length === 0
      && run.error !== null;
    const isSkippedValid = run.completed_at !== null
      && run.source_observed_at === null
      && run.source_watermarks === null
      && run.table_counts.length === 0
      && run.error === null;
    const lifecycleIsValid = run.status === "running"
      ? isRunningValid
      : run.status === "succeeded"
        ? isSucceededValid
        : run.status === "failed"
          ? isFailedValid
          : isSkippedValid;

    if (!lifecycleIsValid) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "media sync run fields do not match its lifecycle status",
      });
    }
  });

export const mediaSyncStatusResponseSchema = z
  .object({
    generated_at: isoTimestampSchema,
    mode: z.literal("periodic_snapshot_refresh"),
    latest_run: mediaSyncRunSchema.nullable(),
    latest_success: mediaSyncRunSchema.nullable(),
    target_watermarks: mediaSyncWatermarksSchema,
    article_reconciliation: mediaArticleReconciliationSchema,
    limitations: z.array(nonEmptyTextSchema).min(1),
  })
  .strict()
  .superRefine((response, context) => {
    if (
      response.latest_success !== null
      && response.latest_success.status !== "succeeded"
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_success", "status"],
        message: "latest_success must reference a succeeded media sync run",
      });
    }
  });

export type MediaSyncWatermarks = z.infer<typeof mediaSyncWatermarksSchema>;
export type MediaSyncTableCount = z.infer<typeof mediaSyncTableCountSchema>;
export type MediaSyncRun = z.infer<typeof mediaSyncRunSchema>;
export type MediaSyncStatusResponse = z.infer<typeof mediaSyncStatusResponseSchema>;

export const mediaSyncStatusEndpoint = "/api/v2/media/sync-status";

export function fetchMediaSyncStatus(signal: AbortSignal): Promise<MediaSyncStatusResponse> {
  return getJson(mediaSyncStatusEndpoint, mediaSyncStatusResponseSchema, signal);
}
