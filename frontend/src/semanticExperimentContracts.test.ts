import { describe, expect, it } from "vitest";

import {
  semanticExperimentCreateRequestSchema,
  semanticExperimentComparisonSchema,
  semanticExperimentDetailSchema,
  semanticReadinessSchema,
  semanticTrialEventSchema,
  semanticTrialResultSchema,
} from "./semanticExperimentContracts";

const ids = {
  experiment: "2ce907de-4709-4eb6-b702-abac631607c7",
  scenario: "d2b8ae09-213d-447d-907f-3c948ea137fc",
  cohort: "84bd015b-8fbf-4227-9598-0b9efe9ef339",
  baseline: "8be40902-8f5a-4569-85c3-bccfd9a07a1b",
  alternative: "8be40902-8f5a-4569-85c3-bccfd9a07a1c",
  baselineTrial: "462bb353-59f3-4737-8199-95f7402885c5",
  alternativeTrial: "462bb353-59f3-4737-8199-95f7402885c6",
  persona: "31552c58-c5c9-4526-9300-ab6eaf982687",
} as const;

const digest = "a".repeat(64);
const anotherDigest = "b".repeat(64);
const timestamp = "2026-08-12T10:00:00+00:00";

function createReadiness(): Record<string, unknown> {
  return {
    engine: "camel-oasis",
    engine_version: "0.2.5",
    camel_version: "0.2.78",
    worker_online: true,
    live_worker_count: 1,
    semantic_runtime_ready: true,
    configuration_conflict: false,
    model_name: "verified-model",
    semantic_config_sha256: digest,
    prompt_schema_version: "matraix-semantic-profile/v1",
    limitations: ["Observed simulation actions are not real-world predictions."],
  };
}

function createResult(userCount: number): Record<string, unknown> {
  return {
    engine_version: "0.2.5",
    camel_version: "0.2.78",
    model_name: "verified-model",
    semantic_config_sha256: digest,
    prompt_schema_version: "matraix-semantic-profile/v1",
    artifact_sha256: anotherDigest,
    artifact_size_bytes: 1024,
    user_count: userCount,
    initial_post_count: 1,
    generated_post_count: 2,
    comment_count: 3,
    reaction_count: 4,
    do_nothing_count: 5,
    observed_action_count: 15,
    authored_content_count: 5,
    rounds_completed: 2,
    limitations: ["Synthetic audience only."],
  };
}

function createDetail(): Record<string, unknown> {
  const trial = (id: string): Record<string, unknown> => ({
    id,
    status: "succeeded",
    seed: 7,
    trial_sha256: digest,
    current_round: 2,
    created_at: timestamp,
    started_at: timestamp,
    completed_at: timestamp,
    result: createResult(3),
    error: null,
  });

  return {
    id: ids.experiment,
    status: "succeeded",
    created_at: timestamp,
    scenario: {
      id: ids.scenario,
      title: "已冻结实验",
      decision_question: "在相同人群中，备选方案和基线发生了哪些可观察动作？",
      scenario_sha256: digest,
    },
    cohort: {
      id: ids.cohort,
      title: "双人观察组",
      cohort_sha256: digest,
      dataset_sha256: anotherDigest,
      persona_count: 2,
    },
    variant_count: 2,
    trial_count: 2,
    rounds: 2,
    minutes_per_round: 60,
    seeds: [7],
    model_name: "verified-model",
    semantic_config_sha256: digest,
    prompt_schema_version: "matraix-semantic-profile/v1",
    experiment_sha256: anotherDigest,
    variants: [
      {
        position: 0,
        role: "baseline",
        id: ids.baseline,
        scenario_position: 0,
        name: "保持现状",
        hypothesis: "不注入初始动作。",
        intervention_count: 0,
        trials: [trial(ids.baselineTrial)],
      },
      {
        position: 1,
        role: "alternative",
        id: ids.alternative,
        scenario_position: 1,
        name: "公开解释",
        hypothesis: "以一条已冻结初始帖子开始。",
        intervention_count: 1,
        trials: [trial(ids.alternativeTrial)],
      },
    ],
  };
}

function createEvent(actionType: string): Record<string, unknown> {
  return {
    sequence: 1,
    round: 1,
    phase: "audience",
    actor_kind: "persona",
    persona_id: ids.persona,
    agent_position: 1,
    action_type: actionType,
    content: null,
    post_id: null,
    comment_id: null,
    target_post_id: null,
    observed_at_raw: "2026-08-12 10:00:00",
    recorded_at: timestamp,
  };
}

describe("semantic experiment contracts", () => {
  it("requires unique alternatives and seeds in the create request", () => {
    expect(semanticExperimentCreateRequestSchema.safeParse({
      scenario_id: ids.scenario,
      cohort_id: ids.cohort,
      alternative_ids: [ids.alternative, ids.alternative],
      seeds: [7, 7],
      rounds: 2,
      minutes_per_round: 60,
    }).success).toBe(false);
  });

  it("accepts the scenario actor plus eight personas and rejects too few users", () => {
    expect(semanticTrialResultSchema.safeParse(createResult(9)).success).toBe(true);
    expect(semanticTrialResultSchema.safeParse(createResult(1)).success).toBe(false);
  });

  it("rejects inconsistent readiness state", () => {
    expect(semanticReadinessSchema.safeParse(createReadiness()).success).toBe(true);
    expect(semanticReadinessSchema.safeParse({
      ...createReadiness(),
      worker_online: false,
    }).success).toBe(false);
    expect(semanticReadinessSchema.safeParse({
      ...createReadiness(),
      configuration_conflict: true,
    }).success).toBe(false);
    expect(semanticReadinessSchema.safeParse({
      ...createReadiness(),
      semantic_runtime_ready: false,
      configuration_conflict: true,
    }).success).toBe(false);
    expect(semanticReadinessSchema.safeParse({
      ...createReadiness(),
      semantic_runtime_ready: false,
      configuration_conflict: true,
      model_name: null,
      semantic_config_sha256: null,
      prompt_schema_version: null,
    }).success).toBe(true);
    expect(semanticReadinessSchema.safeParse({
      ...createReadiness(),
      model_name: null,
    }).success).toBe(false);
  });

  it("binds successful trial dimensions and provenance to the experiment", () => {
    expect(semanticExperimentDetailSchema.safeParse(createDetail()).success).toBe(true);

    const wrongUsers = createDetail();
    const variants = wrongUsers.variants as Array<Record<string, unknown>>;
    const trials = variants[0]?.trials as Array<Record<string, unknown>>;
    trials[0] = { ...trials[0], result: createResult(4) };
    expect(semanticExperimentDetailSchema.safeParse(wrongUsers).success).toBe(false);

    const wrongModel = createDetail();
    const wrongModelVariants = wrongModel.variants as Array<Record<string, unknown>>;
    const wrongModelTrials = wrongModelVariants[1]?.trials as Array<Record<string, unknown>>;
    const result = wrongModelTrials[0]?.result as Record<string, unknown>;
    wrongModelTrials[0] = { ...wrongModelTrials[0], result: { ...result, model_name: "other-model" } };
    expect(semanticExperimentDetailSchema.safeParse(wrongModel).success).toBe(false);
  });

  it("accepts only the exact action-specific event shape", () => {
    expect(semanticTrialEventSchema.safeParse({
      ...createEvent("create_post"),
      content: "真实记录的帖子",
      post_id: "post-1",
    }).success).toBe(true);
    expect(semanticTrialEventSchema.safeParse({
      ...createEvent("create_comment"),
      content: "真实记录的评论",
      comment_id: "comment-1",
      target_post_id: "post-1",
    }).success).toBe(true);
    expect(semanticTrialEventSchema.safeParse({
      ...createEvent("like_post"),
      target_post_id: "post-1",
    }).success).toBe(true);
    expect(semanticTrialEventSchema.safeParse(createEvent("do_nothing")).success).toBe(true);

    expect(semanticTrialEventSchema.safeParse({
      ...createEvent("create_post"),
      content: "缺少 post_id",
    }).success).toBe(false);
    expect(semanticTrialEventSchema.safeParse({
      ...createEvent("create_post"),
      content: "x".repeat(4_001),
      post_id: "post-1",
    }).success).toBe(false);
    expect(semanticTrialEventSchema.safeParse({
      ...createEvent("like_post"),
      content: "反应不允许携带正文",
      target_post_id: "post-1",
    }).success).toBe(false);
    expect(semanticTrialEventSchema.safeParse({
      ...createEvent("do_nothing"),
      target_post_id: "post-1",
    }).success).toBe(false);
    expect(semanticTrialEventSchema.safeParse({
      ...createEvent("create_post"),
      phase: "intervention",
      actor_kind: "persona",
      content: "身份与阶段不匹配",
      post_id: "post-1",
    }).success).toBe(false);
  });

  it("accepts a terminal failed comparison with no successful samples", () => {
    expect(semanticExperimentComparisonSchema.safeParse({
      experiment_id: ids.experiment,
      complete: false,
      state: "failed",
      metrics: [
        "observed_action_count",
        "authored_content_count",
        "reaction_count",
        "do_nothing_count",
      ].map((metric) => ({ metric, variants: [], paired_deltas: [] })),
      limitations: ["No successful trials were available."],
    }).success).toBe(true);
  });
});
