import { z } from "zod";

const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);
const refSchema = z.object({
  id: z.string().uuid(),
});

export const researchEvaluationTaskBundleSchema = z.object({
  id: z.string().uuid(),
  research_project_id: z.string().uuid(),
  research_simulation_run_id: z.string().uuid(),
  cohort_id: z.string().uuid(),
  payload: z.object({
    schema_version: z.literal("sandowl-research-evaluation-task-bundle/v1"),
    kind: z.literal("survey"),
    project_sha256: sha256Schema,
    run_spec_sha256: sha256Schema,
    cohort_sha256: sha256Schema,
    dataset_sha256: sha256Schema,
    instrument_schema_version: z.literal("single-context-observation/v1"),
    instrument_sha256: sha256Schema,
    persona_profile_sha256s: z.array(sha256Schema).min(1).max(8),
    verifier_schema_version: z.literal("research-survey-structural-verifier/v1"),
    trajectory_schema_version: z.literal("ordered-persona-observations/v1"),
    artifact_schema_version: z.literal("sandowl-research-survey-artifact/v1"),
    reward_policy: z.literal("not_applicable"),
    limitations: z.array(z.string().min(1)).min(1),
  }).strict(),
  bundle_sha256: sha256Schema,
  execution: z.object({
    evaluation_id: z.string().uuid(),
    status: z.enum(["queued", "running", "succeeded", "failed"]),
    evaluation_sha256: sha256Schema,
    verifier_state: z.enum(["pending", "passed", "failed"]),
    trajectory_state: z.enum(["empty", "partial", "complete"]),
    recorded_observation_count: z.number().int().min(0).max(24),
    artifact_state: z.enum(["unavailable", "partial", "sealed"]),
    artifact_sha256: sha256Schema.nullable(),
    reward_mode: z.literal("not_applicable"),
    reward_value: z.null(),
  }).strict().nullable(),
  created_at: z.string().datetime({ offset: true }),
  sealed_at: z.string().datetime({ offset: true }),
}).strict();

export const researchEvaluationJobSchema = z.object({
  id: z.string().uuid(),
  research_project_id: z.string().uuid(),
  research_simulation_run_id: z.string().uuid(),
  cohort_id: z.string().uuid(),
  target_id: z.string().uuid(),
  kind: z.enum(["chat", "web", "app"]),
  status: z.enum(["queued", "dispatching", "running", "succeeded", "failed", "cancelled"]),
  job_sha256: sha256Schema,
  retry_of_job_id: z.string().uuid().nullable(),
  retry_of_job_sha256: sha256Schema.nullable(),
  attempt_number: z.number().int().min(1).max(5),
  remote_run_id: z.string().nullable(),
  trajectory_sha256: sha256Schema.nullable(),
  artifact_sha256: sha256Schema.nullable(),
  verifier_sha256: sha256Schema.nullable(),
  reward_sha256: sha256Schema.nullable(),
  reward_value: z.number().min(0).max(1).nullable(),
  created_at: z.string().datetime({ offset: true }),
  started_at: z.string().datetime({ offset: true }).nullable(),
  completed_at: z.string().datetime({ offset: true }).nullable(),
  error_code: z.string().nullable(),
  error_message: z.string().nullable(),
}).strict().superRefine((job, context) => {
  const hasParent = job.retry_of_job_id !== null && job.retry_of_job_sha256 !== null;
  if ((job.attempt_number === 1) === hasParent) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Harbor Job retry lineage is invalid" });
  }
});

export const researchEvaluationWorkspaceSchema = z.object({
  schema_version: z.literal("sandowl-research-evaluation-workspace/v1"),
  project: refSchema.extend({ title: z.string().min(1), project_sha256: sha256Schema }),
  run: refSchema.extend({ run_spec_sha256: sha256Schema, status: z.literal("succeeded") }),
  cohort: refSchema.extend({
    title: z.string().min(1),
    cohort_sha256: sha256Schema,
    dataset_sha256: sha256Schema,
    persona_count: z.number().int().min(1).max(8),
  }),
  persona_quality: z.object({
    selection_method: z.enum(["graph_match", "frozen_cohort"]),
    graph_origin_sha256: sha256Schema.nullable(),
    profile_count: z.number().int().min(1).max(8),
    populated_profile_count: z.number().int().min(0).max(8),
    minimum_dimension_count: z.number().int().min(0).max(1290),
    maximum_dimension_count: z.number().int().min(0).max(1290),
    quality_state: z.enum(["verified", "limited"]),
    explanation: z.string().min(1),
  }),
  task_bundles: z.array(researchEvaluationTaskBundleSchema).max(1),
  targets: z.array(z.object({
    id: z.string().uuid(),
    research_project_id: z.string().uuid(),
    research_simulation_run_id: z.string().uuid(),
    cohort_id: z.string().uuid(),
    payload: z.object({
      schema_version: z.literal("sandowl-research-evaluation-target/v1"),
      kind: z.enum(["chat", "web", "app"]),
      project_sha256: sha256Schema,
      run_spec_sha256: sha256Schema,
      cohort_sha256: sha256Schema,
      dataset_sha256: sha256Schema,
      title: z.string().min(1).max(200),
      target_url: z.string().min(8).max(500).nullable(),
      task_package: z.string().min(1).max(300).nullable(),
      transport: z.enum([
        "rest_chat",
        "mcp_streamable_http",
        "playwright_browser",
        "harbor_task",
      ]),
      task_goal: z.string().min(1).max(2000),
      success_criteria: z.array(z.string().min(1).max(1000)).min(1).max(8),
      verifier_schema_version: z.enum([
        "research-chat-outcome-verifier/v1",
        "research-web-evidence-verifier/v1",
        "research-app-artifact-verifier/v1",
      ]),
      execution_policy: z.literal("definition_only"),
      limitations: z.array(z.string().min(1)).min(1),
    }).strict(),
    target_sha256: sha256Schema,
    created_at: z.string().datetime({ offset: true }),
    sealed_at: z.string().datetime({ offset: true }),
  }).strict()).max(3),
  jobs: z.array(researchEvaluationJobSchema).max(20),
  capabilities: z.array(z.object({
    kind: z.enum(["survey", "chat", "web", "app", "linux"]),
    title: z.string().min(1),
    integration_state: z.enum([
      "native_bound",
      "target_defined",
      "source_sample_only",
      "not_implemented",
    ]),
    can_launch_for_scope: z.boolean(),
    existing_run_count: z.number().int().nonnegative(),
    explanation: z.string().min(1),
  })).length(5),
  runtime_boundaries: z.array(z.object({
    name: z.enum(["task_bundle", "job_runtime", "verifier", "trajectory", "artifact", "reward"]),
    state: z.enum(["available", "partial", "missing"]),
    explanation: z.string().min(1),
  })).length(6),
  limitations: z.array(z.string().min(1)).min(1),
});

export type ResearchEvaluationWorkspace = z.infer<typeof researchEvaluationWorkspaceSchema>;
export type ResearchEvaluationTaskBundle = z.infer<typeof researchEvaluationTaskBundleSchema>;
export type ResearchEvaluationJob = z.infer<typeof researchEvaluationJobSchema>;
export type ResearchEvaluationTarget = ResearchEvaluationWorkspace["targets"][number];
export type ResearchEvaluationTargetKind = ResearchEvaluationTarget["payload"]["kind"];

export async function fetchResearchEvaluationWorkspace(
  projectId: string,
  runId: string,
  signal: AbortSignal,
): Promise<ResearchEvaluationWorkspace> {
  const parameters = new URLSearchParams({ project_id: projectId, run_id: runId });
  const response = await fetch(`/api/v2/research-evaluations/workspace?${parameters}`, { signal });
  if (!response.ok) {
    throw new Error(`读取研究评测上下文失败（HTTP ${response.status}）`);
  }
  return researchEvaluationWorkspaceSchema.parse(await response.json());
}

export async function createResearchEvaluationTaskBundle(
  projectId: string,
  runId: string,
  signal: AbortSignal,
): Promise<ResearchEvaluationTaskBundle> {
  const response = await fetch("/api/v2/research-evaluations/task-bundles", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      research_project_id: projectId,
      research_simulation_run_id: runId,
      kind: "survey",
    }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`准备研究评测任务包失败（HTTP ${response.status}）`);
  }
  return researchEvaluationTaskBundleSchema.parse(await response.json());
}

export async function createResearchEvaluationTarget(
  request: {
    readonly research_project_id: string;
    readonly research_simulation_run_id: string;
    readonly kind: ResearchEvaluationTargetKind;
    readonly title: string;
    readonly target_url: string | null;
    readonly task_package: string | null;
    readonly transport: "rest_chat" | "mcp_streamable_http" | "playwright_browser" | "harbor_task";
    readonly task_goal: string;
    readonly success_criteria: readonly string[];
  },
  signal: AbortSignal,
): Promise<ResearchEvaluationTarget> {
  const response = await fetch("/api/v2/research-evaluations/targets", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    throw new Error(`封存研究被测对象失败（HTTP ${response.status}）`);
  }
  const workspaceTargetSchema = researchEvaluationWorkspaceSchema.shape.targets.element;
  return workspaceTargetSchema.parse(await response.json());
}

export async function createResearchEvaluationJob(
  projectId: string,
  runId: string,
  targetId: string,
  signal: AbortSignal,
): Promise<ResearchEvaluationJob> {
  const response = await fetch("/api/v2/research-evaluations/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      research_project_id: projectId,
      research_simulation_run_id: runId,
      target_id: targetId,
    }),
    signal,
  });
  if (!response.ok) throw new Error(`提交 Harbor Job 失败（HTTP ${response.status}）`);
  return researchEvaluationJobSchema.parse(await response.json());
}

export async function retryResearchEvaluationJob(
  jobId: string,
  signal: AbortSignal,
): Promise<ResearchEvaluationJob> {
  const response = await fetch(`/api/v2/research-evaluations/jobs/${jobId}/retry`, {
    method: "POST",
    signal,
  });
  if (!response.ok) throw new Error(`重试 Harbor Job 失败（HTTP ${response.status}）`);
  return researchEvaluationJobSchema.parse(await response.json());
}
