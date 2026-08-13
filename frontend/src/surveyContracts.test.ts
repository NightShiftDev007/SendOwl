import { describe, expect, it } from "vitest";

import { surveyReadinessSchema, surveyTrialSchema } from "./surveyContracts";

const digest = "a".repeat(64);
const persona = { id: "d43de43d-c71e-4986-9b67-bd08ce096616", position: 0, persona_id: "persona-1", display_name: "Persona 1", profile_sha256: digest };

describe("MatrAIx Survey contracts", () => {
  it("accepts a complete runtime readiness identity", () => {
    expect(surveyReadinessSchema.parse({
      engine: "matraix-survey", runner_version: "1.0.0", worker_online: true, live_worker_count: 1,
      survey_runtime_ready: true, configuration_conflict: false, model_name: "qwen", survey_config_sha256: digest,
      prompt_schema_version: "matraix-survey-scenario-preference/v1", instrument_schema_version: "scenario-preference/v1",
      limitations: ["Synthetic Persona responses are not human research."],
    }).survey_runtime_ready).toBe(true);
  });

  it("rejects readiness without a complete provider identity", () => {
    expect(surveyReadinessSchema.safeParse({
      engine: "matraix-survey", runner_version: "1.0.0", worker_online: true, live_worker_count: 1,
      survey_runtime_ready: true, configuration_conflict: false, model_name: null, survey_config_sha256: null,
      prompt_schema_version: null, instrument_schema_version: "scenario-preference/v1", limitations: ["Synthetic."],
    }).success).toBe(false);
  });

  it("rejects a succeeded trial with a missing required answer", () => {
    expect(surveyTrialSchema.safeParse({
      id: "b9f503c2-0fa0-47d2-96b2-bec014440822", status: "succeeded", persona, trial_sha256: digest,
      created_at: "2026-08-13T00:00:00Z", started_at: "2026-08-13T00:00:01Z", completed_at: "2026-08-13T00:00:02Z", error: null,
      result: { runner_version: "1.0.0", model_name: "qwen", survey_config_sha256: digest, prompt_schema_version: "matraix-survey-scenario-preference/v1", answers_sha256: digest, answers: [
        { position: 0, question_id: "preferred_variant", type: "single_choice", value: "baseline" },
        { position: 1, question_id: "alternative_support", type: "likert", value: 3 },
      ] },
    }).success).toBe(false);
  });
});
