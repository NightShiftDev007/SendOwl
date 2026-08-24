import { describe, expect, it } from "vitest";

import {
  createTrialArchiveEndpoint,
  trialIntegrityVerificationSchema,
  trialArchiveResponseSchema,
  trialArchiveItemSchema,
  surveyTrialArchiveItemSchema,
} from "./trialArchiveContracts";

const digest = "a".repeat(64);
const secondDigest = "b".repeat(64);
const surveyTrialId = "2ce907de-4709-4eb6-b702-abac631607c7";
const chatTrialId = "ff51bd82-385d-48ad-aa3c-9277dd927380";
const persona = {
  id: "d43de43d-c71e-4986-9b67-bd08ce096616",
  position: 0,
  persona_id: "persona-1",
  display_name: "Persona 1",
  profile_sha256: digest,
};
const twoItemStatistics = {
  total: 2,
  by_kind: { survey: 1, chat: 1, web: 0, linux: 0 },
  by_status: { queued: 0, running: 0, succeeded: 1, failed: 1 },
} as const;

const succeededSurvey = {
  kind: "survey",
  id: surveyTrialId,
  status: "succeeded",
  parent_id: "b9f503c2-0fa0-47d2-96b2-bec014440822",
  parent_sha256: secondDigest,
  trial_sha256: digest,
  task: { title: "Scenario preference", version: "scenario-preference/v1" },
  persona,
  created_at: "2026-08-13T10:00:00Z",
  started_at: "2026-08-13T10:00:01Z",
  completed_at: "2026-08-13T10:00:02Z",
  error: null,
  provenance: {
    runner_version: "1.0.0",
    model_name: "qwen-plus",
    parent_config_sha256: digest,
    prompt_schema_version: "matraix-survey-scenario-preference/v1",
    answers_sha256: secondDigest,
  },
  source_detail_path: `/api/v2/matraix/survey-trials/${surveyTrialId}`,
} as const;

const failedChat = {
  kind: "chat",
  id: chatTrialId,
  status: "failed",
  parent_id: "5e3baa67-60c8-4a88-a320-5d3478346a11",
  parent_sha256: digest,
  trial_sha256: secondDigest,
  task: { title: "Acme support: late order #4521", version: "1.0.0" },
  persona,
  created_at: "2026-08-13T09:00:00Z",
  started_at: "2026-08-13T09:00:01Z",
  completed_at: "2026-08-13T09:00:02Z",
  error: { code: "sidecar_unavailable", message: "Acme sidecar returned HTTP 503." },
  provenance: {
    runner_version: null,
    model_name: "qwen-plus",
    parent_config_sha256: secondDigest,
    prompt_schema_version: "matraix-chat-acme-support/v1",
    transcript_sha256: null,
    feedback_sha256: null,
    result_sha256: null,
  },
  source_detail_path: `/api/v2/matraix/chat-trials/${chatTrialId}`,
} as const;

const succeededWeb = {
  ...succeededSurvey,
  kind: "web",
  id: "3ce907de-4709-4eb6-b702-abac631607c7",
  task: { title: "Quote to save", version: "1.0.0" },
  provenance: {
    runner_version: "1.0.0",
    model_name: "qwen-plus",
    parent_config_sha256: digest,
    prompt_schema_version: "matraix-web-quotes-choice/v1",
    trace_sha256: digest,
    result_sha256: secondDigest,
  },
  source_detail_path: "/api/v2/matraix/web-trials/3ce907de-4709-4eb6-b702-abac631607c7",
} as const;

const queuedLinux = {
  ...failedChat,
  kind: "linux",
  id: "4ce907de-4709-4eb6-b702-abac631607c7",
  status: "queued",
  parent_id: "6e3baa67-60c8-4a88-a320-5d3478346a11",
  task: { title: "Note to CSV cleanup", version: "1.0.0" },
  started_at: null,
  completed_at: null,
  error: null,
  provenance: {
    runner_version: null,
    model_name: "qwen-plus",
    parent_config_sha256: digest,
    prompt_schema_version: "matraix-linux-note-to-csv/v1",
    artifact_sha256: null,
    result_sha256: null,
  },
  source_detail_path: "/api/v2/matraix/linux-trials/4ce907de-4709-4eb6-b702-abac631607c7",
} as const;

describe("MatrAIx Trial Archive contracts", () => {
  it("accepts a native Research Survey trial linked to its parent detail", () => {
    expect(surveyTrialArchiveItemSchema.parse({
      ...succeededSurvey,
      task: { title: "Native research project", version: "single-context-observation/v1" },
      provenance: {
        ...succeededSurvey.provenance,
        prompt_schema_version: "sandowl-research-survey/v1",
      },
      source_detail_path: `/api/v2/research-surveys/${succeededSurvey.parent_id}`,
    }).task.version).toBe("single-context-observation/v1");
  });

  it("parses kind-discriminated Survey and Chat provenance", () => {
    expect(trialArchiveItemSchema.parse(succeededSurvey).kind).toBe("survey");
    expect(trialArchiveItemSchema.parse(failedChat).kind).toBe("chat");
  });

  it("parses Web and Linux without flattening their output hashes", () => {
    expect(trialArchiveItemSchema.parse(succeededWeb).kind).toBe("web");
    expect(trialArchiveItemSchema.parse(queuedLinux).kind).toBe("linux");
  });

  it("rejects a succeeded item without every required output hash", () => {
    expect(trialArchiveItemSchema.safeParse({
      ...succeededSurvey,
      provenance: { ...succeededSurvey.provenance, answers_sha256: null },
    }).success).toBe(false);
  });

  it("rejects a Chat archive item whose frozen task title changed", () => {
    expect(trialArchiveItemSchema.safeParse({
      ...failedChat,
      task: { ...failedChat.task, title: "A different task" },
    }).success).toBe(false);
  });

  it("rejects timestamps that violate the durable lifecycle order", () => {
    expect(trialArchiveItemSchema.safeParse({
      ...succeededSurvey,
      started_at: "2026-08-13T09:59:59Z",
    }).success).toBe(false);
    expect(trialArchiveItemSchema.safeParse({
      ...succeededSurvey,
      completed_at: "2026-08-13T10:00:00Z",
    }).success).toBe(false);
  });

  it("rejects a source detail path that does not identify the exact trial", () => {
    expect(trialArchiveItemSchema.safeParse({
      ...failedChat,
      source_detail_path: "/api/v2/matraix/chat-trials/2ce907de-4709-4eb6-b702-abac631607c7",
    }).success).toBe(false);
  });

  it("accepts explicit paging metadata and server ordering", () => {
    expect(trialArchiveResponseSchema.parse({
      items: [succeededSurvey, failedChat],
      page: 1,
      page_size: 20,
      total: 2,
      statistics: twoItemStatistics,
    }).total).toBe(2);
  });

  it("accepts an explicit empty page beyond the final record without inventing navigation", () => {
    expect(trialArchiveResponseSchema.parse({
      items: [],
      page: 4,
      page_size: 20,
      total: 2,
      statistics: twoItemStatistics,
    })).toMatchObject({ page: 4, total: 2 });
  });

  it("rejects a total smaller than the records actually returned", () => {
    expect(trialArchiveResponseSchema.safeParse({
      items: [succeededSurvey, failedChat],
      page: 1,
      page_size: 20,
      total: 1,
      statistics: twoItemStatistics,
    }).success).toBe(false);
  });

  it("rejects archive items returned out of documented order", () => {
    expect(trialArchiveResponseSchema.safeParse({
      items: [failedChat, succeededSurvey],
      page: 1,
      page_size: 20,
      total: 2,
      statistics: twoItemStatistics,
    }).success).toBe(false);
  });

  it("orders aware timestamps by instant instead of their textual offset", () => {
    const laterSurvey = {
      ...succeededSurvey,
      created_at: "2026-08-13T10:30:00+01:00",
    };
    const earlierChat = {
      ...failedChat,
      created_at: "2026-08-13T10:00:00+01:00",
    };
    expect(trialArchiveResponseSchema.safeParse({
      items: [laterSurvey, earlierChat],
      page: 1,
      page_size: 20,
      total: 2,
      statistics: twoItemStatistics,
    }).success).toBe(true);
  });

  it("rejects aggregate counts that do not reconcile to the filtered total", () => {
    expect(trialArchiveResponseSchema.safeParse({
      items: [succeededSurvey, failedChat],
      page: 1,
      page_size: 20,
      total: 2,
      statistics: {
        ...twoItemStatistics,
        by_status: { ...twoItemStatistics.by_status, failed: 0 },
      },
    }).success).toBe(false);
  });

  it("builds a bounded endpoint without empty optional parameters", () => {
    expect(createTrialArchiveEndpoint({
      page: 3,
      pageSize: 20,
      kind: "chat",
      status: "failed",
    })).toBe("/api/v2/matraix/trials?page=3&page_size=20&kind=chat&status=failed");
    expect(createTrialArchiveEndpoint({
      page: 1,
      pageSize: 20,
      kind: null,
      status: null,
    })).toBe("/api/v2/matraix/trials?page=1&page_size=20");
  });

  it("parses exact Survey verification checks without treating them as reward", () => {
    const verification = trialIntegrityVerificationSchema.parse({
      kind: "survey",
      trial_id: surveyTrialId,
      status: "succeeded",
      verification: "verified",
      verified_at: "2026-08-13T10:00:03Z",
      checks: [
        { name: "sealed_parent", status: "passed", content_sha256: digest },
        { name: "trial_address", status: "passed", content_sha256: secondDigest },
        { name: "state_shape", status: "passed", content_sha256: null },
        { name: "survey_answers", status: "passed", content_sha256: digest },
      ],
      limitations: [
        "Verification proves stored content-address integrity.",
        "A verified Trial is not a benchmark reward.",
      ],
    });
    expect(verification.checks.map((check) => check.name)).toEqual([
      "sealed_parent",
      "trial_address",
      "state_shape",
      "survey_answers",
    ]);
  });

  it("rejects reordered or fabricated integrity checks", () => {
    expect(trialIntegrityVerificationSchema.safeParse({
      kind: "chat",
      trial_id: chatTrialId,
      status: "failed",
      verification: "verified",
      verified_at: "2026-08-13T10:00:03Z",
      checks: [
        { name: "sealed_parent", status: "passed", content_sha256: digest },
        { name: "trial_address", status: "passed", content_sha256: secondDigest },
        { name: "state_shape", status: "passed", content_sha256: null },
        { name: "chat_feedback", status: "not_applicable", content_sha256: null },
        { name: "chat_transcript", status: "not_applicable", content_sha256: null },
        { name: "chat_result", status: "not_applicable", content_sha256: null },
      ],
      limitations: ["One limitation.", "Another limitation."],
    }).success).toBe(false);
  });
});
