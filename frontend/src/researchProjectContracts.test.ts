import { describe, expect, it } from "vitest";

import {
  researchProjectCreateRequestSchema,
  researchProjectAgendaContextSchema,
  researchProjectSchema,
  researchRunCreateRequestSchema,
  researchRunReportsResponseSchema,
} from "./researchProjectContracts";

const identity = "2ce907de-4709-4eb6-b702-abac631607c7";
const secondIdentity = "ff51bd82-385d-48ad-aa3c-9277dd927380";
const digest = "a".repeat(64);

describe("research project contracts", () => {
  it("accepts one Project / Graph context without a run design", () => {
    expect(researchProjectSchema.parse({
      id: identity,
      title: "单次模拟研究",
      research_question: "合成人群产生了哪些动作？",
      snapshot: {
        world_model_id: identity,
        world_snapshot_id: secondIdentity,
        snapshot_sha256: digest,
      },
      graph: null,
      schema_version: "sandowl-research-project/v2",
      legacy_design: null,
      project_sha256: digest,
      created_at: "2026-08-16T12:00:00+08:00",
    }).schema_version).toBe("sandowl-research-project/v2");
  });

  it("rejects an unspecified comparison field", () => {
    expect(() => researchProjectCreateRequestSchema.parse({
      title: "单次模拟研究",
      research_question: "合成人群产生了哪些动作？",
      world_model_id: identity,
      world_snapshot_id: secondIdentity,
      comparison_matrix: [],
    })).toThrow();
  });

  it("accepts an immutable AgendaScope context without invented topics", () => {
    expect(researchProjectAgendaContextSchema.parse({
      project_id: identity,
      project_sha256: digest,
      payload: {
        schema_version: "sandowl-project-agenda-context/v1",
        snapshot_sha256: digest,
        frozen_article_ids: [secondIdentity],
        topics: [],
        source_sync_run_id: null,
        source_observed_at: null,
        limitations: ["冻结快照没有关联已导入议题。"],
      },
      context_sha256: digest,
      captured_at: "2026-08-18T12:00:00+08:00",
    }).payload.topics).toEqual([]);
  });

  it("requires one explicit initial context for an independent run", () => {
    expect(researchRunCreateRequestSchema.parse({
      cohort_id: identity,
      simulation_requirement: "运行一次有界群体模拟。",
      seed: 7,
      planning_mode: "manual",
      rounds: 1,
      minutes_per_round: 60,
      time_horizon_minutes: null,
      activity_intensity: null,
      initial_post: "虚构机构发布一条合成说明。",
      scheduled_posts: [],
    }).rounds).toBe(1);
  });

  it("accepts a native report directory item without the event stream", () => {
    const project = {
      id: identity,
      title: "单次模拟研究",
      research_question: "合成人群产生了哪些动作？",
      snapshot: {
        world_model_id: identity,
        world_snapshot_id: secondIdentity,
        snapshot_sha256: digest,
      },
      graph: null,
      schema_version: "sandowl-research-project/v2",
      legacy_design: null,
      project_sha256: digest,
      created_at: "2026-08-16T12:00:00+08:00",
    } as const;
    const run = {
      id: secondIdentity,
      research_project_id: identity,
      project_sha256: digest,
      schema_version: "sandowl-research-simulation-run/v2",
      cohort: { cohort_id: identity, cohort_sha256: digest, persona_count: 2 },
      simulation_requirement: "观察一次独立模拟。",
      seed: 7,
      rounds: 1,
      minutes_per_round: 60,
      initial_post: "虚构机构发布一条说明。",
      engine: "camel-oasis",
      engine_version: "0.2.5",
      model_name: "test-model",
      semantic_config_sha256: digest,
      prompt_schema_version: "matraix-semantic-profile/v1",
      simulation_context: null,
      simulation_context_sha256: null,
      simulation_plan: null,
      simulation_plan_sha256: null,
      status: "succeeded",
      run_spec_sha256: digest,
      created_at: "2026-08-16T12:00:00+08:00",
      started_at: "2026-08-16T12:01:00+08:00",
      completed_at: "2026-08-16T12:02:00+08:00",
      result: {
        artifact_sha256: digest,
        artifact_size_bytes: 128,
        user_count: 3,
        initial_post_count: 1,
        generated_post_count: 0,
        comment_count: 0,
        reaction_count: 0,
        do_nothing_count: 2,
        observed_action_count: 3,
        rounds_completed: 1,
        limitations: ["仅描述一次合成运行。"],
      },
      error: null,
    } as const;

    expect(researchRunReportsResponseSchema.parse({
      items: [{
        id: identity,
        research_project: project,
        run,
        report_sha256: digest,
        created_at: "2026-08-16T12:02:00+08:00",
      }],
      total: 1,
    }).total).toBe(1);
  });
});
