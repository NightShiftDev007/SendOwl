import { describe, expect, it } from "vitest";

import { webEvaluationDetailSchema, webReadinessSchema, webTrialSchema } from "./webEvaluationContracts";

const digest = "a".repeat(64);
const timestamp = "2026-08-15T08:00:00Z";
const evaluationId = "21000000-0000-4000-8000-000000000001";
const trialId = "22000000-0000-4000-8000-000000000001";
const personaId = "23000000-0000-4000-8000-000000000001";

const task = {
  task_id: "matraix/quotes-playwright-choice",
  version: "1.0.0",
  schema_version: "matraix-web-task/quote-choice-v1",
  title: "Quote to save",
  domain: "arts-culture",
  source: {
    kind: "source_sample",
    project: "MatrAIx",
    canonical_path: "application/tasks/example-web-playwright_quote-choice",
    production_sut: false,
  },
  transport: "playwright_chromium",
  target_origin: "https://quotes.toscrape.com",
  instruction: "Choose one observed quote.",
  context: "Compare the three bounded pages.",
  page_count: 3,
  maximum_quote_count: 60,
  task_spec_sha256: digest,
  executor_schema_version: "matraix-web-browser-executor/v1",
  executor_spec_sha256: digest,
  limitations: ["This is a fixed source sample, not unrestricted browsing."],
} as const;

const persona = {
  id: personaId,
  position: 0,
  persona_id: "persona-1",
  display_name: "Persona One",
  profile_sha256: digest,
} as const;

const trialSummary = {
  id: trialId,
  status: "queued",
  persona,
  trial_sha256: digest,
  created_at: timestamp,
  started_at: null,
  completed_at: null,
  observed_page_count: 0,
  observed_quote_count: 0,
  selected_quote_id: null,
  error: null,
} as const;

const evaluation = {
  id: evaluationId,
  status: "queued",
  created_at: timestamp,
  task,
  cohort: {
    id: "24000000-0000-4000-8000-000000000001",
    title: "Web cohort",
    cohort_sha256: digest,
    dataset_sha256: digest,
    persona_count: 1,
  },
  trial_count: 1,
  succeeded_trial_count: 0,
  failed_trial_count: 0,
  model_name: "qwen-plus",
  web_config_sha256: digest,
  prompt_schema_version: "matraix-web-quotes-choice/v1",
  evaluation_sha256: digest,
  retry_of_evaluation_id: null,
  retry_of_evaluation_sha256: null,
  attempt_number: 1,
  trials: [trialSummary],
} as const;

describe("MatrAIx Web contracts", () => {
  it("accepts a queued evaluation with a frozen Persona", () => {
    expect(webEvaluationDetailSchema.parse(evaluation).id).toBe(evaluationId);
  });

  it("rejects summary counts or state that disagree with trials", () => {
    expect(webEvaluationDetailSchema.safeParse({
      ...evaluation,
      status: "succeeded",
      succeeded_trial_count: 1,
    }).success).toBe(false);
  });

  it("rejects a selected quote that was not observed", () => {
    expect(webTrialSchema.safeParse({
      ...trialSummary,
      status: "succeeded",
      started_at: timestamp,
      completed_at: timestamp,
      pages: [],
      result: {
        runner_version: "1.0.0",
        model_name: "qwen-plus",
        web_config_sha256: digest,
        prompt_schema_version: "matraix-web-quotes-choice/v1",
        trace_sha256: digest,
        result_sha256: digest,
        decision_subject_id: digest,
        decision_subject_label: "Unobserved quote",
        decision_outcome: "selected",
        basis_primary: "fit",
        exploration_style: "compared_multiple",
        reason: "This unobserved quote must not be accepted by the contract.",
        task_author: "Unknown",
        need_constraint_satisfaction: "yes",
        personal_preference_satisfaction: "yes",
        overall_experience_rating: 8,
      },
      error: null,
    }).success).toBe(false);
  });

  it("requires readiness identity exactly when the runtime is ready", () => {
    expect(webReadinessSchema.safeParse({
      engine: "matraix-web-playwright",
      runner_version: "1.0.0",
      worker_online: true,
      live_worker_count: 1,
      web_runtime_ready: false,
      configuration_conflict: false,
      model_name: "qwen-plus",
      web_config_sha256: digest,
      prompt_schema_version: "matraix-web-quotes-choice/v1",
      task,
      limitations: ["Runtime configuration must be complete."],
    }).success).toBe(false);
  });
});
