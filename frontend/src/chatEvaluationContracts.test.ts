import { describe, expect, it } from "vitest";

import {
  chatEvaluationDetailSchema,
  chatReadinessSchema,
  chatTranscriptDeltaSchema,
  chatTrialAtifProjectionSchema,
  chatTrialSchema,
  matraixChatTaskSchema,
  mergeChatTranscriptDelta,
} from "./chatEvaluationContracts";

const digest = "a".repeat(64);
const otherDigest = "b".repeat(64);
const task = {
  task_id: "matraix/acme-support-order-4521",
  version: "1.0.0",
  schema_version: "matraix-chat-task/acme-support-v1",
  title: "Acme support: late order #4521",
  domain: "commerce-retail",
  source: {
    kind: "source_sample",
    project: "MatrAIx",
    canonical_path: "application/tasks/example-chat-api_support_chatbot",
    production_sut: false,
  },
  application_id: "acme_support_api",
  application_context: "customer_support",
  transport: "sidecar_http",
  capabilities: ["text_chat"],
  instruction: "Ask Acme Support for a useful resolution path.",
  context: "Order #4521 is late.",
  minimum_customer_turns: 2,
  minimum_total_messages: 4,
  feedback_schema_version: "matraix-chat-feedback/acme-support-v1",
  task_spec_sha256: digest,
  sut_spec_sha256: otherDigest,
  limitations: ["This is a source sample, not a production SUT."],
} as const;
const mcpTask = {
  ...task,
  task_id: "matraix/acme-support-mcp-order-4521",
  source: {
    ...task.source,
    canonical_path: "application/tasks/example-chat-mcp_support_chatbot",
  },
  application_id: "acme_support_mcp",
  transport: "mcp_streamable_http",
  capabilities: ["text_chat", "mcp_tool"],
} as const;
const persona = {
  id: "d43de43d-c71e-4986-9b67-bd08ce096616",
  position: 0,
  persona_id: "persona-1",
  display_name: "Persona 1",
  profile_sha256: digest,
};
const transcript = [
  { position: 0, role: "customer", content: "Where is order #4521?", recorded_at: "2026-08-13T00:00:01Z" },
  { position: 1, role: "support", content: "I can check. What address was used?", recorded_at: "2026-08-13T00:00:02Z" },
  { position: 2, role: "customer", content: "The address on the order is current.", recorded_at: "2026-08-13T00:00:03Z" },
  { position: 3, role: "support", content: "Tracking is delayed; check again tomorrow.", recorded_at: "2026-08-13T00:00:04Z" },
] as const;
const feedback = {
  schema_version: "matraix-chat-feedback/acme-support-v1",
  need_constraint_satisfaction: "partially",
  personal_preference_satisfaction: "yes",
  overall_experience_rating: 6,
  reason: "The response gave me a concrete next step.",
  asked_useful_clarification_questions: true,
  clarifying_notes: "The address check was relevant.",
} as const;
const result = {
  runner_version: "1.0.0",
  model_name: "qwen-plus",
  chat_config_sha256: digest,
  prompt_schema_version: "matraix-chat-acme-support/v1",
  transcript_sha256: digest,
  feedback_sha256: otherDigest,
  result_sha256: digest,
  outcome_status: "partially_resolved",
  next_step_owner: "user",
  conversation_path: "clarify_then_partial",
  resolution_progression: "advanced",
  message_count: 4,
  customer_turn_count: 2,
  support_turn_count: 2,
  clarification_question_count: 1,
} as const;
const succeededTrial = {
  id: "b9f503c2-0fa0-47d2-96b2-bec014440822",
  status: "succeeded",
  persona,
  trial_sha256: digest,
  created_at: "2026-08-13T00:00:00Z",
  started_at: "2026-08-13T00:00:01Z",
  completed_at: "2026-08-13T00:00:05Z",
  transcript,
  feedback,
  result,
  error: null,
} as const;

describe("MatrAIx Chat Evaluation contracts", () => {
  it("accepts the complete source-sample identity including task and SUT digests", () => {
    const parsed = matraixChatTaskSchema.parse(task);
    expect(parsed.source).toMatchObject({ kind: "source_sample", production_sut: false });
    expect(parsed.sut_spec_sha256).toBe(otherDigest);
  });

  it("accepts a complete live readiness identity and rejects partial configuration", () => {
    expect(chatReadinessSchema.parse({
      engine: "matraix-chat",
      runner_version: "1.0.0",
      worker_online: true,
      live_worker_count: 1,
      chat_runtime_ready: true,
      configuration_conflict: false,
      model_name: "qwen-plus",
      chat_config_sha256: digest,
      prompt_schema_version: "matraix-chat-acme-support/v1",
      tasks: [task, mcpTask],
      limitations: ["Synthetic Persona feedback is not human research."],
    }).chat_runtime_ready).toBe(true);

    expect(chatReadinessSchema.safeParse({
      engine: "matraix-chat",
      runner_version: "1.0.0",
      worker_online: true,
      live_worker_count: 1,
      chat_runtime_ready: false,
      configuration_conflict: false,
      model_name: "qwen-plus",
      chat_config_sha256: null,
      prompt_schema_version: null,
      tasks: [task, mcpTask],
      limitations: ["Synthetic."],
    }).success).toBe(false);
  });

  it("accepts a succeeded trial only when transcript and verifier counts agree", () => {
    expect(chatTrialSchema.parse(succeededTrial).result?.message_count).toBe(4);

    expect(chatTrialSchema.safeParse({
      ...succeededTrial,
      result: { ...result, message_count: 6 },
    }).success).toBe(false);
  });

  it("retains a failed partial transcript without accepting feedback or result", () => {
    expect(chatTrialSchema.parse({
      ...succeededTrial,
      status: "failed",
      completed_at: "2026-08-13T00:00:03Z",
      transcript: transcript.slice(0, 2),
      feedback: null,
      result: null,
      error: { code: "sidecar_unavailable", message: "Acme sidecar returned HTTP 503." },
    }).transcript).toHaveLength(2);
  });

  it("accepts an exact ATIF-v1.7 transcript projection without invented telemetry", () => {
    const projection = {
      projection_schema_version: "sandowl-chat-atif-projection/v1",
      projection_sha256: digest,
      completeness: "complete",
      source_trial_sha256: otherDigest,
      source_transcript_sha256: digest,
      limitations: [
        "Derived from recorded transcript.",
        "Synthetic Persona messages.",
        "No unrecorded telemetry is inferred.",
      ],
      trajectory: {
        schema_version: "ATIF-v1.7",
        session_id: succeededTrial.id,
        trajectory_id: `urn:sha256:${digest}`,
        agent: { name: "Acme support source sample", version: "1.0.0" },
        steps: transcript.map((message, index) => index % 2 === 0 ? {
          step_id: index + 1,
          timestamp: message.recorded_at,
          source: "user",
          message: message.content,
        } : {
          step_id: index + 1,
          timestamp: message.recorded_at,
          source: "agent",
          message: message.content,
          llm_call_count: 0,
        }),
        notes: "Observed transcript projection.",
        final_metrics: { total_steps: 4 },
      },
    };

    expect(chatTrialAtifProjectionSchema.parse(projection).trajectory.steps).toHaveLength(4);
    expect(chatTrialAtifProjectionSchema.safeParse({
      ...projection,
      trajectory: {
        ...projection.trajectory,
        steps: projection.trajectory.steps.map((step, index) => (
          index === 1 ? { ...step, llm_call_count: 1 } : step
        )),
      },
    }).success).toBe(false);
  });

  it("rejects a transcript that does not alternate customer then support", () => {
    expect(chatTrialSchema.safeParse({
      ...succeededTrial,
      transcript: transcript.map((message, index) => (
        index === 1 ? { ...message, role: "customer" } : message
      )),
    }).success).toBe(false);
  });

  it("merges a monotonic transcript delta idempotently", () => {
    const runningTrial = {
      ...succeededTrial,
      status: "running",
      completed_at: null,
      transcript: transcript.slice(0, 1),
      feedback: null,
      result: null,
      error: null,
    } as const;
    const detail = chatEvaluationDetailSchema.parse({
      id: "2ce907de-4709-4eb6-b702-abac631607c7",
      status: "running",
      created_at: "2026-08-13T00:00:00Z",
      task,
      cohort: {
        id: "782eb270-3504-45bd-9336-3ed88f48f71d",
        title: "Chat Cohort",
        cohort_sha256: digest,
        dataset_sha256: otherDigest,
        persona_count: 1,
      },
      trial_count: 1,
      succeeded_trial_count: 0,
      failed_trial_count: 0,
      model_name: "qwen-plus",
      chat_config_sha256: digest,
      prompt_schema_version: "matraix-chat-acme-support/v1",
      evaluation_sha256: digest,
      retry_of_evaluation_id: null,
      retry_of_evaluation_sha256: null,
      attempt_number: 1,
      trials: [runningTrial],
    });
    const delta = chatTranscriptDeltaSchema.parse({
      evaluation_id: detail.id,
      after_event_sequence: "0",
      next_event_sequence: "102",
      items: [
        {
          event_sequence: "101",
          trial_id: runningTrial.id,
          message: transcript[0],
        },
        {
          event_sequence: "102",
          trial_id: runningTrial.id,
          message: transcript[1],
        },
      ],
      observed_at: "2026-08-13T00:00:03Z",
    });

    expect(mergeChatTranscriptDelta(detail, delta).trials.at(0)?.transcript).toHaveLength(2);
    expect(chatTranscriptDeltaSchema.safeParse({
      ...delta,
      next_event_sequence: "101",
    }).success).toBe(false);
  });

  it("requires detail trials to match frozen Cohort order and terminal counts", () => {
    const detail = {
      id: "2ce907de-4709-4eb6-b702-abac631607c7",
      status: "succeeded",
      created_at: "2026-08-13T00:00:00Z",
      task,
      cohort: {
        id: "ff51bd82-385d-48ad-aa3c-9277dd927380",
        title: "Support cohort",
        cohort_sha256: digest,
        dataset_sha256: otherDigest,
        persona_count: 1,
      },
      trial_count: 1,
      succeeded_trial_count: 1,
      failed_trial_count: 0,
      model_name: "qwen-plus",
      chat_config_sha256: digest,
      prompt_schema_version: "matraix-chat-acme-support/v1",
      evaluation_sha256: otherDigest,
      retry_of_evaluation_id: null,
      retry_of_evaluation_sha256: null,
      attempt_number: 1,
      trials: [succeededTrial],
    } as const;
    expect(chatEvaluationDetailSchema.parse(detail).trials).toHaveLength(1);
    expect(chatEvaluationDetailSchema.parse({
      ...detail,
      id: "2ce907de-4709-4eb6-b702-abac631607c8",
      retry_of_evaluation_id: detail.id,
      retry_of_evaluation_sha256: detail.evaluation_sha256,
      attempt_number: 2,
    }).attempt_number).toBe(2);
    expect(chatEvaluationDetailSchema.safeParse({
      ...detail,
      attempt_number: 2,
    }).success).toBe(false);
    expect(chatEvaluationDetailSchema.safeParse({
      ...detail,
      succeeded_trial_count: 0,
      failed_trial_count: 1,
    }).success).toBe(false);
  });
});
