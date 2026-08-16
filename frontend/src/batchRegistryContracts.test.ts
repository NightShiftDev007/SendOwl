import { describe, expect, it } from "vitest";

import {
  createBatchRegistriesEndpoint,
  createBatchRegistryCandidatesEndpoint,
  matraixBatchRegistriesResponseSchema,
  matraixBatchRegistryCandidateSchema,
  matraixBatchRegistryCreateRequestSchema,
  matraixBatchRegistryDetailSchema,
  matraixBatchRegistryItemSchema,
  matraixNativeBatchLaunchRequestSchema,
  matraixNativeBatchLaunchResultSchema,
} from "./batchRegistryContracts";

const registryId = "2ce907de-4709-4eb6-b702-abac631607c7";
const surveyId = "ff51bd82-385d-48ad-aa3c-9277dd927380";
const chatId = "af9b38d8-f040-4284-a1f5-b3e7ecf18066";
const webId = "bf9b38d8-f040-4284-a1f5-b3e7ecf18067";
const linuxId = "cf9b38d8-f040-4284-a1f5-b3e7ecf18068";
const digestA = "a".repeat(64);
const digestB = "b".repeat(64);
const digestC = "c".repeat(64);

const surveyCandidate = {
  kind: "survey",
  parent_id: surveyId,
  parent_sha256: digestA,
  title: "Scenario preference: baseline vs alternative",
  version: "scenario-preference/v1",
  observed_status: "succeeded",
  created_at: "2026-08-13T08:00:00Z",
  trial_count: 2,
  succeeded_trial_count: 2,
  failed_trial_count: 0,
  model_name: "qwen-plus",
  parent_config_sha256: digestB,
  prompt_schema_version: "matraix-survey-scenario-preference/v1",
  source_detail_path: `/api/v2/matraix/survey-experiments/${surveyId}`,
} as const;

const chatCandidate = {
  kind: "chat",
  parent_id: chatId,
  parent_sha256: digestB,
  title: "Acme support: late order #4521",
  version: "1.0.0",
  observed_status: "failed",
  created_at: "2026-08-13T07:00:00Z",
  trial_count: 2,
  succeeded_trial_count: 1,
  failed_trial_count: 1,
  model_name: "qwen-plus",
  parent_config_sha256: digestC,
  prompt_schema_version: "matraix-chat-acme-support/v1",
  source_detail_path: `/api/v2/matraix/chat-evaluations/${chatId}`,
} as const;

const webCandidate = {
  kind: "web",
  parent_id: webId,
  parent_sha256: digestC,
  title: "Quote to save",
  version: "1.0.0",
  observed_status: "queued",
  created_at: "2026-08-13T06:00:00Z",
  trial_count: 1,
  succeeded_trial_count: 0,
  failed_trial_count: 0,
  model_name: "qwen-plus",
  parent_config_sha256: digestA,
  prompt_schema_version: "matraix-web-quotes-choice/v1",
  source_detail_path: `/api/v2/matraix/web-evaluations/${webId}`,
} as const;

const linuxCandidate = {
  kind: "linux",
  parent_id: linuxId,
  parent_sha256: digestA,
  title: "Note to CSV cleanup",
  version: "1.0.0",
  observed_status: "queued",
  created_at: "2026-08-13T05:00:00Z",
  trial_count: 1,
  succeeded_trial_count: 0,
  failed_trial_count: 0,
  model_name: "qwen-plus",
  parent_config_sha256: digestB,
  prompt_schema_version: "matraix-linux-note-to-csv/v1",
  source_detail_path: `/api/v2/matraix/linux-evaluations/${linuxId}`,
} as const;

const summary = {
  id: registryId,
  title: "Frozen comparison registry",
  registry_state: "sealed",
  execution_kind: "registry_only",
  observed_trial_status: "failed",
  observed_at: "2026-08-13T08:20:00Z",
  created_at: "2026-08-13T08:10:00Z",
  sealed_at: "2026-08-13T08:10:01Z",
  registry_sha256: digestC,
  item_count: 2,
  trial_count: 4,
  succeeded_trial_count: 3,
  failed_trial_count: 1,
} as const;

describe("MatrAIx Batch Registry contracts", () => {
  it("accepts exact kind-specific candidate contracts", () => {
    expect(matraixBatchRegistryCandidateSchema.parse(surveyCandidate).kind).toBe("survey");
    expect(matraixBatchRegistryCandidateSchema.parse(chatCandidate).kind).toBe("chat");
    expect(matraixBatchRegistryCandidateSchema.parse(webCandidate).kind).toBe("web");
    expect(matraixBatchRegistryCandidateSchema.parse(linuxCandidate).kind).toBe("linux");
    expect(matraixBatchRegistryItemSchema.parse({ ...webCandidate, position: 0 }).kind)
      .toBe("web");
  });

  it("rejects candidate task identity drift and an inconsistent observed status", () => {
    expect(matraixBatchRegistryCandidateSchema.safeParse({
      ...chatCandidate,
      title: "A different task",
    }).success).toBe(false);
    expect(matraixBatchRegistryCandidateSchema.safeParse({
      ...surveyCandidate,
      observed_status: "succeeded",
      succeeded_trial_count: 1,
    }).success).toBe(false);
  });

  it("requires contiguous ordered items and reproduces registry observations", () => {
    const detail = {
      ...summary,
      items: [
        { ...surveyCandidate, position: 0 },
        { ...chatCandidate, position: 1 },
      ],
    };
    expect(matraixBatchRegistryDetailSchema.parse(detail).observed_trial_status).toBe("failed");
    expect(matraixBatchRegistryDetailSchema.safeParse({
      ...detail,
      observed_trial_status: "succeeded",
    }).success).toBe(false);
    expect(matraixBatchRegistryItemSchema.safeParse({
      ...surveyCandidate,
      position: 1,
      source_detail_path: `/api/v2/matraix/chat-evaluations/${surveyId}`,
    }).success).toBe(false);
  });

  it("requires a top-level dynamic observation timestamp on directory responses", () => {
    expect(matraixBatchRegistriesResponseSchema.parse({
      items: [summary],
      page: 1,
      page_size: 20,
      total: 1,
      observed_at: "2026-08-13T08:20:00Z",
    }).observed_at).toBe("2026-08-13T08:20:00Z");
    expect(matraixBatchRegistriesResponseSchema.safeParse({
      items: [summary],
      page: 1,
      page_size: 20,
      total: 1,
    }).success).toBe(false);
    expect(matraixBatchRegistriesResponseSchema.safeParse({
      items: [{ ...summary, observed_at: "2026-08-13T08:21:00Z" }],
      page: 1,
      page_size: 20,
      total: 1,
      observed_at: "2026-08-13T08:20:00Z",
    }).success).toBe(false);
  });

  it("rejects duplicate typed parents in a create request", () => {
    expect(matraixBatchRegistryCreateRequestSchema.safeParse({
      title: "Duplicate registry",
      items: [
        { kind: "survey", parent_id: surveyId },
        { kind: "survey", parent_id: surveyId },
      ],
    }).success).toBe(false);
  });

  it("builds bounded registry and candidate endpoints", () => {
    expect(createBatchRegistriesEndpoint({ page: 2, pageSize: 20 }))
      .toBe("/api/v2/matraix/batch-registries?page=2&page_size=20");
    expect(createBatchRegistryCandidatesEndpoint({ page: 3, pageSize: 20, kind: "chat" }))
      .toBe("/api/v2/matraix/batch-registry-candidates?page=3&page_size=20&kind=chat");
    expect(createBatchRegistryCandidatesEndpoint({ page: 1, pageSize: 20, kind: "web" }))
      .toBe("/api/v2/matraix/batch-registry-candidates?page=1&page_size=20&kind=web");
    expect(createBatchRegistryCandidatesEndpoint({ page: 1, pageSize: 20, kind: "linux" }))
      .toBe("/api/v2/matraix/batch-registry-candidates?page=1&page_size=20&kind=linux");
  });

  it("validates ordered native Survey and Chat launch specs", () => {
    const request = {
      title: "Native release",
      items: [
        {
          kind: "survey" as const,
          scenario_id: "23000000-0000-4000-8000-000000000001",
          cohort_id: "24000000-0000-4000-8000-000000000001",
          alternative_id: "25000000-0000-4000-8000-000000000001",
        },
        {
          kind: "chat" as const,
          cohort_id: "24000000-0000-4000-8000-000000000001",
          task_id: "matraix/acme-support-order-4521" as const,
          task_version: "1.0.0" as const,
        },
      ],
    };
    expect(matraixNativeBatchLaunchRequestSchema.parse(request).items.map((item) => item.kind))
      .toEqual(["survey", "chat"]);
    expect(matraixNativeBatchLaunchRequestSchema.safeParse({
      title: "Duplicate",
      items: [request.items[0], request.items[0]],
    }).success).toBe(false);
    expect(matraixNativeBatchLaunchRequestSchema.safeParse({
      title: "Linux remains registry-only",
      items: [{
        kind: "linux",
        cohort_id: "24000000-0000-4000-8000-000000000001",
        persona_id: "24000000-0000-4000-8000-000000000002",
        task_id: "matraix/linux-note-to-csv",
        task_version: "1.0.0",
      }],
    }).success).toBe(false);
    expect(matraixNativeBatchLaunchRequestSchema.safeParse({
      title: "Web remains registry-only",
      items: [{
        kind: "web",
        cohort_id: "24000000-0000-4000-8000-000000000001",
        task_id: "matraix/quotes-playwright-choice",
        task_version: "1.0.0",
      }],
    }).success).toBe(false);
    expect(matraixNativeBatchLaunchResultSchema.parse({
      launch_mode: "native_parent_enqueue",
      registry: {
        ...summary,
        items: [
          { ...surveyCandidate, position: 0 },
          { ...chatCandidate, position: 1 },
        ],
      },
    }).registry.execution_kind).toBe("registry_only");
  });
});
