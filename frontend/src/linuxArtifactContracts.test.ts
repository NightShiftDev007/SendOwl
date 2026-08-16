import { describe, expect, it } from "vitest";

import {
  linuxEvaluationSchema,
  linuxReadinessSchema,
  linuxTaskSchema,
  linuxTrialSchema,
} from "./linuxArtifactContracts";

const task = {
  task_id: "matraix/linux-note-to-csv",
  version: "1.0.0",
  schema_version: "matraix-linux-task/note-to-csv-v1",
  title: "Note to CSV cleanup",
  domain: "software",
  source: {
    kind: "source_sample",
    project: "MatrAIx",
    canonical_path: "application/tasks/example-computer-use-linux_note-to-csv",
    production_sut: false,
  },
  execution_kind: "linux_artifact_runner",
  computer_use: false,
  instruction: "Create the fixed CSV.",
  context: "Three fixed rows.",
  required_artifacts: ["cleaned_list.csv", "submission.json", "user_feedback.json", "verifier.json"],
  task_spec_sha256: "a".repeat(64),
  runner_schema_version: "matraix-linux-artifact-runner/v1",
  runner_spec_sha256: "b".repeat(64),
  limitations: ["No shell or Computer Use."],
} as const;

describe("Linux artifact contracts", () => {
  it("accepts the fixed source task and honest blocked readiness", () => {
    expect(linuxTaskSchema.parse(task).computer_use).toBe(false);
    expect(linuxReadinessSchema.parse({
      engine: "matraix-linux-artifact",
      runner_version: "1.0.0",
      worker_online: true,
      live_worker_count: 1,
      linux_runtime_ready: false,
      configuration_conflict: false,
      model_name: null,
      linux_config_sha256: null,
      prompt_schema_version: null,
      task,
      limitations: ["Model is not configured."],
    }).linux_runtime_ready).toBe(false);
  });

  it("rejects a succeeded trial without verified result fields", () => {
    expect(() => linuxTrialSchema.parse({
      id: "33000000-0000-4000-8000-000000000001",
      status: "succeeded",
      created_at: "2026-08-15T00:00:00Z",
      started_at: "2026-08-15T00:00:01Z",
      completed_at: "2026-08-15T00:00:02Z",
      task,
      cohort: {
        id: "34000000-0000-4000-8000-000000000001",
        title: "Cohort",
        cohort_sha256: "c".repeat(64),
        dataset_sha256: "d".repeat(64),
      },
      persona: {
        id: "35000000-0000-4000-8000-000000000001",
        position: 0,
        persona_id: "persona-1",
        display_name: "Persona One",
        profile_sha256: "e".repeat(64),
      },
      trial_sha256: "f".repeat(64),
      retry_of_trial_id: null,
      retry_of_trial_sha256: null,
      attempt_number: 1,
      result: null,
      error: null,
    })).toThrow();
  });

  it("accepts a sealed single-Trial evaluation parent", () => {
    const trial = {
      id: "33000000-0000-4000-8000-000000000001",
      status: "queued",
      created_at: "2026-08-15T00:00:00Z",
      started_at: null,
      completed_at: null,
      task,
      cohort: {
        id: "34000000-0000-4000-8000-000000000001",
        title: "Cohort",
        cohort_sha256: "c".repeat(64),
        dataset_sha256: "d".repeat(64),
      },
      persona: {
        id: "35000000-0000-4000-8000-000000000001",
        position: 0,
        persona_id: "persona-1",
        display_name: "Persona One",
        profile_sha256: "e".repeat(64),
      },
      trial_sha256: "f".repeat(64),
      retry_of_trial_id: null,
      retry_of_trial_sha256: null,
      attempt_number: 1,
      result: null,
      error: null,
    } as const;
    expect(linuxEvaluationSchema.parse({
      id: "36000000-0000-4000-8000-000000000001",
      status: "queued",
      execution_kind: "linux_artifact_runner",
      registry_eligibility: "sealed_parent",
      created_at: "2026-08-15T00:00:01Z",
      sealed_at: "2026-08-15T00:00:01Z",
      evaluation_sha256: "1".repeat(64),
      trial,
    }).trial.id).toBe(trial.id);
  });
});
