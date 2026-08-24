import { describe, expect, it } from "vitest";

import {
  researchSurveyDetailSchema,
  researchSurveyReadinessSchema,
} from "./researchSurveyContracts";

const id = "10000000-0000-4000-8000-000000000001";
const digest = "a".repeat(64);

describe("native research Survey contracts", () => {
  it("accepts a single-context Survey and rejects ADC variant fields", () => {
    const detail = {
      id,
      status: "queued",
      project: { id, title: "研究项目", research_question: "什么仍不清晰？", project_sha256: digest },
      run: { id, simulation_requirement: "观察一个上下文", initial_post: "单一合成声明", run_spec_sha256: digest },
      cohort: { id, title: "冻结 Cohort", cohort_sha256: digest, dataset_sha256: digest, persona_count: 1 },
      trial_count: 1,
      succeeded_trial_count: 0,
      failed_trial_count: 0,
      model_name: "qwen",
      survey_config_sha256: digest,
      prompt_schema_version: "sandowl-research-survey/v1",
      instrument_schema_version: "single-context-observation/v1",
      instrument_sha256: digest,
      survey_sha256: digest,
      created_at: "2026-08-17T05:00:00+00:00",
      instrument: { schema_version: "single-context-observation/v1", instrument_sha256: digest, title: "Single-context observation", description: "固定三题" },
      trials: [{ id, status: "queued", persona: { id, position: 0, persona_id: "persona-1", display_name: "Persona 1", profile_sha256: digest }, trial_sha256: digest, created_at: "2026-08-17T05:00:00+00:00", started_at: null, completed_at: null, result: null, error: null }],
      aggregate: { succeeded_trial_count: 0, failed_trial_count: 0, context_clarity_mean: null, attention_priority: { evidence: 0, process: 0, timing: 0, impact: 0 }, unanswered_questions: [], limitations: ["Synthetic only."] },
    };

    expect(researchSurveyDetailSchema.safeParse(detail).success).toBe(true);
    expect(researchSurveyDetailSchema.safeParse({ ...detail, alternative: { id } }).success).toBe(false);
  });

  it("requires the native prompt identity in readiness", () => {
    const readiness = { engine: "matraix-survey", runner_version: "1.0.0", survey_runtime_ready: true, live_worker_count: 1, model_name: "qwen", survey_config_sha256: digest, prompt_schema_version: "sandowl-research-survey/v1", instrument_schema_version: "single-context-observation/v1", limitations: ["Synthetic only."] };
    expect(researchSurveyReadinessSchema.safeParse(readiness).success).toBe(true);
    expect(researchSurveyReadinessSchema.safeParse({ ...readiness, prompt_schema_version: "matraix-survey-scenario-preference/v1" }).success).toBe(false);
  });
});
