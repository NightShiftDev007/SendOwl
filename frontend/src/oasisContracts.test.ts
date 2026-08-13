import { describe, expect, it } from "vitest";

import {
  createPlatformSmokeRunDetailEndpoint,
  createPlatformSmokeRunRequestSchema,
  oasisReadinessSchema,
  platformSmokeRunDetailSchema,
  platformSmokeRunSummarySchema,
  platformSmokeRunsResponseSchema,
} from "./oasisContracts";

const runId = "6f22ff11-76ae-4a32-bc4b-7acd80efe19a";
const scenarioId = "16f59066-b4e9-4d71-8c51-7742f85943f2";
const variantId = "02e09ee8-88e8-4831-9427-f891255219ef";
const worldSnapshotId = "33f6aee5-2912-4429-85ab-601dbfe41c19";
const inputDigest = "a".repeat(64);
const scenarioDigest = "b".repeat(64);
const snapshotDigest = "c".repeat(64);
const artifactDigest = "d".repeat(64);

const validReadiness = {
  engine: "camel-oasis",
  engine_version: "0.2.5",
  mode: "reddit_manual_smoke",
  worker_online: true,
  platform_runtime_ready: true,
  semantic_run_ready: false,
  limitations: ["No LLM agents are executed."],
};

const validScenario = {
  id: scenarioId,
  scenario_sha256: scenarioDigest,
  variant_id: variantId,
  variant_name: "主动公开供应链进展",
  world_snapshot_id: worldSnapshotId,
  snapshot_sha256: snapshotDigest,
};

const validSummary = {
  id: runId,
  mode: "reddit_manual_smoke",
  status: "succeeded",
  created_at: "2026-08-12T08:30:00Z",
  started_at: "2026-08-12T08:30:01Z",
  completed_at: "2026-08-12T08:30:02Z",
  scenario: validScenario,
  seed: 4_294_967_295,
  input_sha256: inputDigest,
};

const validDetail = {
  ...validSummary,
  posts: [
    {
      position: 0,
      content: "我们将公开供应链进展并持续更新。",
      offset_minutes: 30,
    },
  ],
  result: {
    engine_version: "0.2.5",
    camel_version: "0.2.78",
    artifact_sha256: artifactDigest,
    artifact_size_bytes: 4_096,
    user_count: 1,
    post_count: 1,
    trace_count: 2,
    limitations: ["Manual platform actions only."],
  },
  error: null,
};

const validRequest = {
  scenario_id: scenarioId,
  variant_id: variantId,
  seed: 7,
};

describe("OASIS platform-smoke contracts", () => {
  it("accepts the exact readiness, list, detail, and create shapes", () => {
    expect(oasisReadinessSchema.safeParse(validReadiness).success).toBe(true);
    expect(platformSmokeRunSummarySchema.safeParse(validSummary).success).toBe(true);
    expect(
      platformSmokeRunsResponseSchema.safeParse({ items: [validSummary], total: 1 }).success,
    ).toBe(true);
    expect(platformSmokeRunDetailSchema.safeParse(validDetail).success).toBe(true);
    expect(createPlatformSmokeRunRequestSchema.safeParse(validRequest).success).toBe(true);
  });

  it("keeps detail-only payloads out of summaries and rejects undeclared fields", () => {
    expect(platformSmokeRunSummarySchema.safeParse(validDetail).success).toBe(false);
    expect(
      createPlatformSmokeRunRequestSchema.safeParse({
        ...validRequest,
        acknowledged: true,
      }).success,
    ).toBe(false);
    expect(
      oasisReadinessSchema.safeParse({
        ...validReadiness,
        semantic_run_ready: true,
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunSummarySchema.safeParse({
        ...validSummary,
        scenario: { ...validScenario, company_name: "removed" },
      }).success,
    ).toBe(false);
  });

  it("pins the real engine versions and manual Reddit mode", () => {
    expect(
      oasisReadinessSchema.safeParse({
        ...validReadiness,
        engine_version: "0.3.0",
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        mode: "semantic_prediction",
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        result: { ...validDetail.result, camel_version: "0.3.0" },
      }).success,
    ).toBe(false);
  });

  it("enforces UUIDs, uint32 seeds, digests, and sequential frozen posts", () => {
    expect(
      createPlatformSmokeRunRequestSchema.safeParse({
        ...validRequest,
        seed: 4_294_967_296,
      }).success,
    ).toBe(false);
    expect(
      createPlatformSmokeRunRequestSchema.safeParse({
        ...validRequest,
        seed: 1.5,
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        input_sha256: "not-a-digest",
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        posts: [
          validDetail.posts[0],
          { ...validDetail.posts[0], position: 2 },
        ],
      }).success,
    ).toBe(false);
  });

  it("accepts failed details only through the explicit error contract", () => {
    const failedDetail = {
      ...validDetail,
      status: "failed",
      result: null,
      error: { code: "oasis_platform_error", message: "SQLite write failed." },
    };

    expect(platformSmokeRunDetailSchema.safeParse(failedDetail).success).toBe(true);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...failedDetail,
        error: { ...failedDetail.error, traceback: "hidden" },
      }).success,
    ).toBe(false);
  });

  it("enforces lifecycle timestamps and mutually exclusive terminal output", () => {
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        status: "queued",
        started_at: null,
        completed_at: null,
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        status: "running",
        completed_at: null,
        result: null,
      }).success,
    ).toBe(true);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        status: "failed",
        result: null,
        error: null,
      }).success,
    ).toBe(false);
  });

  it("enforces backend result and identifier bounds", () => {
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        result: { ...validDetail.result, artifact_size_bytes: 0 },
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        result: { ...validDetail.result, trace_count: 22 },
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        result: { ...validDetail.result, user_count: 2 },
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        result: { ...validDetail.result, post_count: 2, trace_count: 2 },
      }).success,
    ).toBe(false);
    expect(
      platformSmokeRunDetailSchema.safeParse({
        ...validDetail,
        scenario: { ...validScenario, variant_name: "invalid\nname" },
      }).success,
    ).toBe(false);
  });

  it("encodes detail identifiers", () => {
    expect(createPlatformSmokeRunDetailEndpoint("run/中国")).toBe(
      "/api/v2/simulation-runs/platform-smoke/run%2F%E4%B8%AD%E5%9B%BD",
    );
  });
});
