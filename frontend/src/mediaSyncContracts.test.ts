import { describe, expect, it } from "vitest";

import {
  mediaSyncRunSchema,
  mediaSyncStatusEndpoint,
  mediaSyncStatusResponseSchema,
  mediaSyncTableCountSchema,
  mediaSyncTableNames,
} from "./mediaSyncContracts";

const timestamp = "2026-08-13T04:00:00Z";
const watermarks = {
  latest_source_updated_at: timestamp,
  latest_article_crawled_at: timestamp,
  latest_topic_updated_at: timestamp,
  latest_topic_article_assigned_at: timestamp,
  latest_snapshot_created_at: timestamp,
  latest_snapshot_window_end: timestamp,
  latest_propagation_updated_at: null,
};
const articleReconciliation = {
  present_count: 9_500,
  absent_count: 2,
  latest_absent_at: timestamp,
};
const tableCounts = mediaSyncTableNames.map((tableName) => ({
  table_name: tableName,
  read_count: 7,
  inserted_count: 1,
  updated_count: 2,
  skipped_count: 4,
}));
const succeededRun = {
  id: "6de0231e-cc0d-4ae6-a34c-20497d9736df",
  trigger: "scheduled",
  status: "succeeded",
  worker_id: "sandowl-compose-media-sync-worker",
  started_at: "2026-08-13T03:59:50Z",
  completed_at: timestamp,
  next_scheduled_at: "2026-08-13T04:05:00Z",
  source_observed_at: "2026-08-13T03:59:59Z",
  source_watermarks: watermarks,
  table_counts: tableCounts,
  error: null,
};

describe("media sync status contract", () => {
  it("accepts a complete successful snapshot refresh", () => {
    const result = mediaSyncStatusResponseSchema.safeParse({
      generated_at: timestamp,
      mode: "periodic_snapshot_refresh",
      latest_run: succeededRun,
      latest_success: succeededRun,
      target_watermarks: watermarks,
      article_reconciliation: articleReconciliation,
      limitations: [
        "Each refresh scans all supported AgendaScope source rows and only writes changed target rows.",
      ],
    });

    expect(result.success).toBe(true);
    expect(mediaSyncStatusEndpoint).toBe("/api/v2/media/sync-status");
  });

  it("accepts existing imported watermarks before any durable run is recorded", () => {
    expect(
      mediaSyncStatusResponseSchema.safeParse({
        generated_at: timestamp,
        mode: "periodic_snapshot_refresh",
        latest_run: null,
        latest_success: null,
        target_watermarks: watermarks,
        article_reconciliation: articleReconciliation,
        limitations: ["Source deletions are not propagated."],
      }).success,
    ).toBe(true);
  });

  it("requires exact table accounting for every supported table", () => {
    expect(
      mediaSyncTableCountSchema.safeParse({
        ...tableCounts[0],
        read_count: 8,
      }).success,
    ).toBe(false);
    expect(
      mediaSyncRunSchema.safeParse({
        ...succeededRun,
        table_counts: tableCounts.slice(0, -1),
      }).success,
    ).toBe(false);
    expect(
      mediaSyncRunSchema.safeParse({
        ...succeededRun,
        table_counts: [...tableCounts.slice(0, -1), tableCounts[0]],
      }).success,
    ).toBe(false);
  });

  it("rejects fields that contradict each lifecycle state", () => {
    expect(
      mediaSyncRunSchema.safeParse({
        ...succeededRun,
        status: "running",
      }).success,
    ).toBe(false);
    expect(
      mediaSyncRunSchema.safeParse({
        ...succeededRun,
        status: "failed",
        source_observed_at: null,
        source_watermarks: null,
        table_counts: [],
        error: null,
      }).success,
    ).toBe(false);
    expect(
      mediaSyncRunSchema.safeParse({
        ...succeededRun,
        trigger: "manual",
      }).success,
    ).toBe(false);
  });

  it("accepts only the exact field sets for running, failed, and concurrent-skip runs", () => {
    const runningRun = {
      ...succeededRun,
      status: "running",
      completed_at: null,
      next_scheduled_at: null,
      source_observed_at: null,
      source_watermarks: null,
      table_counts: [],
      error: null,
    };
    const failedRun = {
      ...runningRun,
      status: "failed",
      completed_at: timestamp,
      error: { code: "source_unavailable", message: "Source connection failed." },
    };
    const skippedRun = {
      ...runningRun,
      status: "skipped_concurrent",
      completed_at: timestamp,
      next_scheduled_at: "2026-08-13T04:05:00Z",
    };

    expect(mediaSyncRunSchema.safeParse(runningRun).success).toBe(true);
    expect(mediaSyncRunSchema.safeParse(failedRun).success).toBe(true);
    expect(mediaSyncRunSchema.safeParse(skippedRun).success).toBe(true);
    expect(
      mediaSyncRunSchema.safeParse({ ...skippedRun, error: failedRun.error }).success,
    ).toBe(false);
  });

  it("publishes next_scheduled_at only for succeeded or skipped scheduled runs", () => {
    const scheduledRunningRun = {
      ...succeededRun,
      status: "running",
      completed_at: null,
      next_scheduled_at: null,
      source_observed_at: null,
      source_watermarks: null,
      table_counts: [],
      error: null,
    };
    const scheduledFailedRun = {
      ...scheduledRunningRun,
      status: "failed",
      completed_at: timestamp,
      error: { code: "source_unavailable", message: "Source connection failed." },
    };

    expect(mediaSyncRunSchema.safeParse(scheduledRunningRun).success).toBe(true);
    expect(mediaSyncRunSchema.safeParse(scheduledFailedRun).success).toBe(true);
    expect(
      mediaSyncRunSchema.safeParse({
        ...scheduledRunningRun,
        next_scheduled_at: "2026-08-13T04:05:00Z",
      }).success,
    ).toBe(false);
    expect(
      mediaSyncRunSchema.safeParse({
        ...scheduledFailedRun,
        next_scheduled_at: "2026-08-13T04:05:00Z",
      }).success,
    ).toBe(false);
    expect(
      mediaSyncRunSchema.safeParse({ ...succeededRun, next_scheduled_at: null }).success,
    ).toBe(false);
    expect(
      mediaSyncRunSchema.safeParse({
        ...succeededRun,
        status: "skipped_concurrent",
        source_observed_at: null,
        source_watermarks: null,
        table_counts: [],
      }).success,
    ).toBe(true);
  });

  it("never publishes next_scheduled_at for manual runs", () => {
    const manualSucceededRun = {
      ...succeededRun,
      trigger: "manual",
      next_scheduled_at: null,
    };

    expect(mediaSyncRunSchema.safeParse(manualSucceededRun).success).toBe(true);
    expect(
      mediaSyncRunSchema.safeParse({
        ...manualSucceededRun,
        next_scheduled_at: "2026-08-13T04:05:00Z",
      }).success,
    ).toBe(false);
  });

  it("rejects a completion before start and a non-success latest_success", () => {
    expect(
      mediaSyncRunSchema.safeParse({
        ...succeededRun,
        completed_at: "2026-08-13T03:00:00Z",
      }).success,
    ).toBe(false);

    const failedRun = {
      ...succeededRun,
      status: "failed",
      completed_at: timestamp,
      source_observed_at: null,
      source_watermarks: null,
      table_counts: [],
      error: { code: "source_unavailable", message: "Source connection failed." },
    };
    expect(
      mediaSyncStatusResponseSchema.safeParse({
        generated_at: timestamp,
        mode: "periodic_snapshot_refresh",
        latest_run: failedRun,
        latest_success: failedRun,
        target_watermarks: watermarks,
        article_reconciliation: articleReconciliation,
        limitations: ["No deletion propagation."],
      }).success,
    ).toBe(false);
  });

  it("rejects undocumented response fields and unsafe error codes", () => {
    expect(
      mediaSyncStatusResponseSchema.safeParse({
        generated_at: timestamp,
        mode: "periodic_snapshot_refresh",
        latest_run: null,
        latest_success: null,
        target_watermarks: watermarks,
        article_reconciliation: articleReconciliation,
        limitations: ["No deletion propagation."],
        source_database_url: "postgresql://secret",
      }).success,
    ).toBe(false);
    expect(
      mediaSyncRunSchema.safeParse({
        ...succeededRun,
        status: "failed",
        source_observed_at: null,
        source_watermarks: null,
        table_counts: [],
        error: { code: "Unsafe-Code", message: "Failed." },
      }).success,
    ).toBe(false);
  });

  it("requires every target watermark field with an aware timestamp or null", () => {
    const incompleteWatermarks = Object.fromEntries(
      Object.entries(watermarks).filter(([key]) => key !== "latest_snapshot_window_end"),
    );

    expect(
      mediaSyncStatusResponseSchema.safeParse({
        generated_at: timestamp,
        mode: "periodic_snapshot_refresh",
        latest_run: null,
        latest_success: null,
        target_watermarks: incompleteWatermarks,
        article_reconciliation: articleReconciliation,
        limitations: ["No deletion propagation."],
      }).success,
    ).toBe(false);
    expect(
      mediaSyncStatusResponseSchema.safeParse({
        generated_at: timestamp,
        mode: "periodic_snapshot_refresh",
        latest_run: null,
        latest_success: null,
        target_watermarks: {
          ...watermarks,
          latest_article_crawled_at: "2026-08-13T04:00:00",
        },
        article_reconciliation: articleReconciliation,
        limitations: ["No deletion propagation."],
      }).success,
    ).toBe(false);
  });
});
