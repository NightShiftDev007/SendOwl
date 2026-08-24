import { describe, expect, it } from "vitest";

import {
  researchEvaluationJobSchema,
  researchEvaluationWorkspaceSchema,
} from "./researchEvaluationContracts";

describe("researchEvaluationWorkspaceSchema", () => {
  it("separates native-bound tasks from fixed source samples", () => {
    const digest = "a".repeat(64);
    const id = "748de69e-3192-496d-9b2c-6ca72ac85575";
    const workspace = researchEvaluationWorkspaceSchema.parse({
      schema_version: "sandowl-research-evaluation-workspace/v1",
      project: { id, title: "研究", project_sha256: digest },
      run: { id, run_spec_sha256: digest, status: "succeeded" },
      cohort: { id, title: "人群", cohort_sha256: digest, dataset_sha256: digest, persona_count: 5 },
      persona_quality: { selection_method: "graph_match", graph_origin_sha256: digest, profile_count: 5, populated_profile_count: 5, minimum_dimension_count: 40, maximum_dimension_count: 40, quality_state: "verified", explanation: "质量说明" },
      task_bundles: [],
      targets: [],
      jobs: [],
      capabilities: [
        ["survey", "native_bound", true],
        ["chat", "source_sample_only", false],
        ["web", "source_sample_only", false],
        ["app", "not_implemented", false],
        ["linux", "source_sample_only", false],
      ].map(([kind, integration_state, can_launch_for_scope]) => ({
        kind,
        title: String(kind),
        integration_state,
        can_launch_for_scope,
        existing_run_count: 0,
        explanation: "边界说明",
      })),
      runtime_boundaries: ["task_bundle", "job_runtime", "verifier", "trajectory", "artifact", "reward"].map((name) => ({ name, state: "partial", explanation: "边界说明" })),
      limitations: ["合成评测边界"],
    });
    expect(workspace.capabilities.find((item) => item.kind === "survey")?.can_launch_for_scope).toBe(true);
    expect(workspace.capabilities.find((item) => item.kind === "chat")?.can_launch_for_scope).toBe(false);
  });

  it("validates immutable Harbor retry lineage", () => {
    const digest = "a".repeat(64);
    const id = "748de69e-3192-496d-9b2c-6ca72ac85575";
    const root = {
      id,
      research_project_id: id,
      research_simulation_run_id: id,
      cohort_id: id,
      target_id: id,
      kind: "app",
      status: "failed",
      job_sha256: digest,
      retry_of_job_id: null,
      retry_of_job_sha256: null,
      attempt_number: 1,
      remote_run_id: null,
      trajectory_sha256: null,
      artifact_sha256: null,
      verifier_sha256: null,
      reward_sha256: null,
      reward_value: null,
      created_at: "2026-08-20T00:00:00Z",
      started_at: "2026-08-20T00:00:01Z",
      completed_at: "2026-08-20T00:00:02Z",
      error_code: "runtimeerror",
      error_message: "runner failed",
    } as const;

    expect(researchEvaluationJobSchema.parse(root).attempt_number).toBe(1);
    expect(researchEvaluationJobSchema.safeParse({
      ...root,
      attempt_number: 2,
    }).success).toBe(false);
    expect(researchEvaluationJobSchema.parse({
      ...root,
      id: "32f4e1ed-985e-4786-b965-4e37436bda9f",
      job_sha256: "b".repeat(64),
      retry_of_job_id: root.id,
      retry_of_job_sha256: root.job_sha256,
      attempt_number: 2,
    }).attempt_number).toBe(2);
  });
});
