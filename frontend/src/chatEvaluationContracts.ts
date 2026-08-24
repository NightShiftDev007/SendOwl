import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";
import { parentProgressSchema, type ParentProgress } from "./parentProgress";

const tasksEndpoint = "/api/v2/matraix/chat-tasks";
const evaluationsEndpoint = "/api/v2/matraix/chat-evaluations";
const trialsEndpoint = "/api/v2/matraix/chat-trials";
const readinessEndpoint = "/api/v2/matraix/chat-readiness";
const identifierSchema = z.string().uuid();
const pageSchema = z.number().int().positive();
const timestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const singleLineTextSchema = nonEmptyTextSchema.regex(/^[^\r\n]+$/u);
const evaluationStatusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const taskIdSchema = z.enum([
  "matraix/acme-support-order-4521",
  "matraix/acme-support-mcp-order-4521",
]);
const taskVersionSchema = z.literal("1.0.0");
const taskSchemaVersionSchema = z.literal("matraix-chat-task/acme-support-v1");
const feedbackSchemaVersionSchema = z.literal("matraix-chat-feedback/acme-support-v1");
const runnerVersionSchema = z.literal("1.0.0");
const promptSchemaVersionSchema = z.literal("matraix-chat-acme-support/v1");
const identifierTextSchema = z.string()
  .trim()
  .min(1)
  .max(128)
  .regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u);

export const matraixChatTaskSchema = z.object({
  task_id: taskIdSchema,
  version: taskVersionSchema,
  schema_version: taskSchemaVersionSchema,
  title: z.literal("Acme support: late order #4521"),
  domain: z.literal("commerce-retail"),
  source: z.object({
    kind: z.literal("source_sample"),
    project: z.literal("MatrAIx"),
    canonical_path: z.enum([
      "application/tasks/example-chat-api_support_chatbot",
      "application/tasks/example-chat-mcp_support_chatbot",
    ]),
    production_sut: z.literal(false),
  }).strict(),
  application_id: z.enum(["acme_support_api", "acme_support_mcp"]),
  application_context: z.literal("customer_support"),
  transport: z.enum(["sidecar_http", "mcp_streamable_http"]),
  capabilities: z.array(z.enum(["text_chat", "mcp_tool"])).min(1).max(2),
  instruction: nonEmptyTextSchema.max(4_000),
  context: nonEmptyTextSchema.max(4_000),
  minimum_customer_turns: z.literal(2),
  minimum_total_messages: z.literal(4),
  feedback_schema_version: feedbackSchemaVersionSchema,
  task_spec_sha256: sha256DigestSchema,
  sut_spec_sha256: sha256DigestSchema,
  limitations: z.array(nonEmptyTextSchema.max(2_000)).min(1),
}).strict().superRefine((task, context) => {
  const mcp = task.task_id === "matraix/acme-support-mcp-order-4521";
  const expected = {
    path: mcp
      ? "application/tasks/example-chat-mcp_support_chatbot"
      : "application/tasks/example-chat-api_support_chatbot",
    application: mcp ? "acme_support_mcp" : "acme_support_api",
    transport: mcp ? "mcp_streamable_http" : "sidecar_http",
    capabilities: mcp ? ["text_chat", "mcp_tool"] : ["text_chat"],
  } as const;
  if (task.source.canonical_path !== expected.path
    || task.application_id !== expected.application
    || task.transport !== expected.transport
    || task.capabilities.join("\u0000") !== expected.capabilities.join("\u0000")) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["transport"],
      message: "Fixed Chat task fields must match their REST or MCP transport",
    });
  }
});

export const matraixChatTasksResponseSchema = z.object({
  items: z.array(matraixChatTaskSchema),
  total: z.number().int().nonnegative(),
}).strict().superRefine((response, context) => {
  if (response.items.length !== response.total) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["total"],
      message: "Total must equal the complete static chat task catalog length",
    });
  }

  const taskKeys = response.items.map((item) => `${item.task_id}@${item.version}`);
  if (new Set(taskKeys).size !== taskKeys.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Chat task identities must be unique",
    });
  }
});

export const chatCohortRefSchema = z.object({
  id: identifierSchema,
  title: singleLineTextSchema.max(200),
  cohort_sha256: sha256DigestSchema,
  dataset_sha256: sha256DigestSchema,
  persona_count: z.number().int().min(1).max(8),
}).strict();

export const chatPersonaRefSchema = z.object({
  id: identifierSchema,
  position: z.number().int().min(0).max(7),
  persona_id: identifierTextSchema,
  display_name: singleLineTextSchema.max(200),
  profile_sha256: sha256DigestSchema,
}).strict();

export const chatTranscriptMessageSchema = z.object({
  position: z.number().int().min(0).max(39),
  role: z.enum(["customer", "support"]),
  content: nonEmptyTextSchema.max(8_000),
  recorded_at: timestampSchema,
}).strict();

const eventSequenceSchema = z.string().regex(/^(0|[1-9][0-9]{0,18})$/u);
const positiveEventSequenceSchema = z.string().regex(/^[1-9][0-9]{0,18}$/u);

export const chatTranscriptDeltaSchema = z.object({
  evaluation_id: identifierSchema,
  after_event_sequence: eventSequenceSchema,
  next_event_sequence: eventSequenceSchema,
  items: z.array(z.object({
    event_sequence: positiveEventSequenceSchema,
    trial_id: identifierSchema,
    message: chatTranscriptMessageSchema,
  }).strict()).max(320),
  observed_at: timestampSchema,
}).strict().superRefine((delta, context) => {
  const sequences = delta.items.map((item) => BigInt(item.event_sequence));
  const increasing = sequences.every((sequence, index) => (
    index === 0
      ? sequence > BigInt(delta.after_event_sequence)
      : sequence > sequences[index - 1]!
  ));
  if (!increasing) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Transcript delta sequences must be strictly increasing after the cursor",
    });
  }
  const expectedNext = sequences.at(-1)?.toString() ?? delta.after_event_sequence;
  if (delta.next_event_sequence !== expectedNext) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["next_event_sequence"],
      message: "Delta cursor must equal the last observed event sequence",
    });
  }
});

export const chatFeedbackSchema = z.object({
  schema_version: feedbackSchemaVersionSchema,
  need_constraint_satisfaction: z.enum(["yes", "partially", "no"]),
  personal_preference_satisfaction: z.enum(["yes", "partially", "no"]),
  overall_experience_rating: z.number().int().min(1).max(10),
  reason: nonEmptyTextSchema.max(2_000),
  asked_useful_clarification_questions: z.boolean(),
  clarifying_notes: nonEmptyTextSchema.max(2_000),
}).strict();

export const chatTrialResultSchema = z.object({
  runner_version: runnerVersionSchema,
  model_name: singleLineTextSchema.max(200),
  chat_config_sha256: sha256DigestSchema,
  prompt_schema_version: promptSchemaVersionSchema,
  transcript_sha256: sha256DigestSchema,
  feedback_sha256: sha256DigestSchema,
  result_sha256: sha256DigestSchema,
  outcome_status: z.enum(["resolved", "partially_resolved", "unresolved"]),
  next_step_owner: z.enum(["user", "support", "none"]),
  conversation_path: z.enum(["clarify_then_resolve", "clarify_then_partial", "stalled"]),
  resolution_progression: z.enum(["single_response", "looped", "advanced"]),
  message_count: z.number().int().min(4).max(40),
  customer_turn_count: z.number().int().min(2).max(20),
  support_turn_count: z.number().int().min(2).max(20),
  clarification_question_count: z.number().int().min(0).max(20),
}).strict();

const chatTrialObjectSchema = z.object({
  id: identifierSchema,
  status: evaluationStatusSchema,
  persona: chatPersonaRefSchema,
  trial_sha256: sha256DigestSchema,
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  transcript: z.array(chatTranscriptMessageSchema).max(40),
  feedback: chatFeedbackSchema.nullable(),
  result: chatTrialResultSchema.nullable(),
  error: z.object({
    code: identifierTextSchema,
    message: nonEmptyTextSchema.max(4_000),
  }).strict().nullable(),
}).strict();

export const chatTrialSchema = chatTrialObjectSchema.superRefine((trial, context) => {
  const positionsAreContiguous = trial.transcript.every(
    (message, index) => message.position === index,
  );
  if (!positionsAreContiguous) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["transcript"],
      message: "Transcript positions must be contiguous and start at zero",
    });
  }

  const rolesAlternate = trial.transcript.every((message, index) => (
    message.role === (index % 2 === 0 ? "customer" : "support")
  ));
  if (!rolesAlternate) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["transcript"],
      message: "Transcript must alternate customer and support messages",
    });
  }

  if (trial.status === "queued") {
    if (
      trial.started_at !== null
      || trial.completed_at !== null
      || trial.transcript.length > 0
      || trial.feedback !== null
      || trial.result !== null
      || trial.error !== null
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Queued trials cannot expose timestamps or transcript messages",
      });
    }
  } else if (trial.started_at === null) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["started_at"],
      message: "Claimed trials must expose started_at",
    });
  }

  const terminal = trial.status === "succeeded" || trial.status === "failed";
  if (terminal !== (trial.completed_at !== null)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["completed_at"],
      message: "Only terminal trials must expose completed_at",
    });
  }

  if (trial.status === "succeeded") {
    if (trial.feedback === null || trial.result === null || trial.error !== null) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Succeeded trials require feedback and result, and cannot expose an error",
      });
    }

    if (trial.transcript.length < 4) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["transcript"],
        message: "Succeeded trials require at least four transcript messages",
      });
    }
  } else if (trial.feedback !== null || trial.result !== null) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Only succeeded trials may expose feedback or result",
    });
  }

  if ((trial.status === "failed") !== (trial.error !== null)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["error"],
      message: "Only failed trials must expose an error",
    });
  }

  if (trial.result !== null) {
    const customerTurnCount = trial.transcript.filter(
      (message) => message.role === "customer",
    ).length;
    const supportTurnCount = trial.transcript.length - customerTurnCount;

    if (
      trial.result.message_count !== trial.transcript.length
      || trial.result.customer_turn_count !== customerTurnCount
      || trial.result.support_turn_count !== supportTurnCount
      || trial.result.customer_turn_count !== trial.result.support_turn_count
      || trial.result.clarification_question_count > supportTurnCount
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["result"],
        message: "Result counts must be exactly reproducible from the transcript",
      });
    }
  }
});

const atifUserStepSchema = z.object({
  step_id: z.number().int().min(1).max(40),
  timestamp: timestampSchema,
  source: z.literal("user"),
  message: nonEmptyTextSchema,
}).strict();

const atifAgentStepSchema = z.object({
  step_id: z.number().int().min(1).max(40),
  timestamp: timestampSchema,
  source: z.literal("agent"),
  message: nonEmptyTextSchema,
  llm_call_count: z.literal(0),
}).strict();

const atifStepSchema = z.discriminatedUnion("source", [
  atifUserStepSchema,
  atifAgentStepSchema,
]);

const atifTrajectorySchema = z.object({
  schema_version: z.literal("ATIF-v1.7"),
  session_id: identifierSchema,
  trajectory_id: z.string().regex(/^urn:sha256:[a-f0-9]{64}$/u),
  agent: z.object({
    name: z.literal("Acme support source sample"),
    version: z.literal("1.0.0"),
  }).strict(),
  steps: z.array(atifStepSchema).min(1).max(40),
  notes: nonEmptyTextSchema.max(2_000),
  final_metrics: z.object({
    total_steps: z.number().int().min(1).max(40),
  }).strict(),
}).strict().superRefine((trajectory, context) => {
  const invalidStep = trajectory.steps.findIndex((step, index) => (
    step.step_id !== index + 1
    || step.source !== (index % 2 === 0 ? "user" : "agent")
  ));
  if (invalidStep >= 0) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["steps", invalidStep],
      message: "ATIF Chat steps must be contiguous and alternate user then agent",
    });
  }
  if (trajectory.final_metrics.total_steps !== trajectory.steps.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["final_metrics", "total_steps"],
      message: "ATIF total_steps must equal the observed step count",
    });
  }
});

export const chatTrialAtifProjectionSchema = z.object({
  projection_schema_version: z.literal("sandowl-chat-atif-projection/v1"),
  projection_sha256: sha256DigestSchema,
  completeness: z.enum(["complete", "partial"]),
  source_trial_sha256: sha256DigestSchema,
  source_transcript_sha256: sha256DigestSchema,
  limitations: z.array(nonEmptyTextSchema).length(3),
  trajectory: atifTrajectorySchema,
}).strict().superRefine((projection, context) => {
  if (projection.trajectory.trajectory_id !== `urn:sha256:${projection.projection_sha256}`) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["trajectory", "trajectory_id"],
      message: "ATIF trajectory_id must match the projection content address",
    });
  }
  if (projection.completeness === "complete"
    && (projection.trajectory.steps.length < 4 || projection.trajectory.steps.length % 2 !== 0)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["completeness"],
      message: "Complete Chat trajectories require at least two full exchanges",
    });
  }
});

const chatEvaluationSummaryObjectSchema = z.object({
  id: identifierSchema,
  status: evaluationStatusSchema,
  created_at: timestampSchema,
  task: matraixChatTaskSchema,
  cohort: chatCohortRefSchema,
  trial_count: z.number().int().min(1).max(8),
  succeeded_trial_count: z.number().int().min(0).max(8),
  failed_trial_count: z.number().int().min(0).max(8),
  model_name: singleLineTextSchema.max(200),
  chat_config_sha256: sha256DigestSchema,
  prompt_schema_version: promptSchemaVersionSchema,
  evaluation_sha256: sha256DigestSchema,
  retry_of_evaluation_id: identifierSchema.nullable(),
  retry_of_evaluation_sha256: sha256DigestSchema.nullable(),
  attempt_number: z.number().int().min(1).max(5),
}).strict();

function refineEvaluationCounts(
  evaluation: z.infer<typeof chatEvaluationSummaryObjectSchema>,
  context: z.RefinementCtx,
): void {
  const hasRetryParent = evaluation.retry_of_evaluation_id !== null
    && evaluation.retry_of_evaluation_sha256 !== null;
  if ((evaluation.attempt_number === 1) === hasRetryParent) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["attempt_number"],
      message: "Root attempts have no retry parent; later attempts require one",
    });
  }
  if (evaluation.trial_count !== evaluation.cohort.persona_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["trial_count"],
      message: "Trial count must equal the frozen Cohort size",
    });
  }

  const terminalCount = evaluation.succeeded_trial_count + evaluation.failed_trial_count;
  if (terminalCount > evaluation.trial_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["failed_trial_count"],
      message: "Terminal trial counts cannot exceed trial_count",
    });
  }

  if (["succeeded", "failed"].includes(evaluation.status)
    && terminalCount !== evaluation.trial_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["status"],
      message: "Terminal evaluations require every trial to be terminal",
    });
  }
}

export const chatEvaluationSummarySchema = chatEvaluationSummaryObjectSchema
  .superRefine(refineEvaluationCounts);

export const chatEvaluationDetailSchema = chatEvaluationSummaryObjectSchema.extend({
  trials: z.array(chatTrialSchema).min(1).max(8),
}).strict().superRefine((evaluation, context) => {
  refineEvaluationCounts(evaluation, context);

  if (evaluation.trials.length !== evaluation.trial_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["trials"],
      message: "Detail must contain exactly one trial per frozen Persona",
    });
  }

  const positionsAreContiguous = evaluation.trials.every(
    (trial, index) => trial.persona.position === index,
  );
  if (!positionsAreContiguous) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["trials"],
      message: "Trials must follow contiguous frozen Persona order",
    });
  }

  const succeededCount = evaluation.trials.filter(
    (trial) => trial.status === "succeeded",
  ).length;
  const failedCount = evaluation.trials.filter(
    (trial) => trial.status === "failed",
  ).length;
  if (
    succeededCount !== evaluation.succeeded_trial_count
    || failedCount !== evaluation.failed_trial_count
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["trials"],
      message: "Detail terminal counts must match its trials",
    });
  }
});

export const chatEvaluationsResponseSchema = z.object({
  items: z.array(chatEvaluationSummarySchema).max(50),
  page: z.number().int().positive(),
  page_size: z.number().int().min(1).max(50),
  total: z.number().int().nonnegative(),
}).strict().superRefine((response, context) => {
  if (response.items.length > response.total) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["total"],
      message: "Page items cannot exceed the complete chat evaluation count",
    });
  }
});

export const chatReadinessSchema = z.object({
  engine: z.literal("matraix-chat"),
  runner_version: runnerVersionSchema,
  worker_online: z.boolean(),
  live_worker_count: z.number().int().nonnegative(),
  chat_runtime_ready: z.boolean(),
  configuration_conflict: z.boolean(),
  model_name: singleLineTextSchema.max(200).nullable(),
  chat_config_sha256: sha256DigestSchema.nullable(),
  prompt_schema_version: promptSchemaVersionSchema.nullable(),
  tasks: z.array(matraixChatTaskSchema).length(2),
  limitations: z.array(nonEmptyTextSchema.max(2_000)).min(1),
}).strict().superRefine((readiness, context) => {
  const hasCompleteConfiguration = readiness.model_name !== null
    && readiness.chat_config_sha256 !== null
    && readiness.prompt_schema_version !== null;
  const hasAnyConfiguration = readiness.model_name !== null
    || readiness.chat_config_sha256 !== null
    || readiness.prompt_schema_version !== null;
  if (new Set(readiness.tasks.map((task) => task.task_id)).size !== 2) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["tasks"],
      message: "Readiness must bind both fixed Chat tasks",
    });
  }

  if (readiness.worker_online !== (readiness.live_worker_count > 0)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["worker_online"],
      message: "worker_online must equal live_worker_count > 0",
    });
  }

  if (hasAnyConfiguration !== hasCompleteConfiguration) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["chat_config_sha256"],
      message: "Chat configuration identity must be all present or all absent",
    });
  }

  const expectedReadiness = readiness.worker_online
    && !readiness.configuration_conflict
    && hasCompleteConfiguration;
  if (readiness.chat_runtime_ready !== expectedReadiness) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["chat_runtime_ready"],
      message: "Runtime readiness must match a complete live configuration identity",
    });
  }

  if (readiness.chat_runtime_ready
    && (!readiness.worker_online || readiness.configuration_conflict)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["chat_runtime_ready"],
      message: "Ready chat runtime requires a live, conflict-free worker",
    });
  }

  if (!readiness.chat_runtime_ready && hasCompleteConfiguration) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["model_name"],
      message: "An unready chat projection must not expose a selected configuration",
    });
  }
});

export const chatEvaluationCreateRequestSchema = z.object({
  cohort_id: identifierSchema,
  task_id: taskIdSchema,
  task_version: taskVersionSchema,
}).strict();

export type MatraixChatTask = z.infer<typeof matraixChatTaskSchema>;
export type ChatEvaluationSummary = z.infer<typeof chatEvaluationSummarySchema>;
export type ChatEvaluationDetail = z.infer<typeof chatEvaluationDetailSchema>;
export type ChatTranscriptDelta = z.infer<typeof chatTranscriptDeltaSchema>;
export type ChatTrial = z.infer<typeof chatTrialSchema>;
export type ChatTrialAtifProjection = z.infer<typeof chatTrialAtifProjectionSchema>;
export type ChatReadiness = z.infer<typeof chatReadinessSchema>;
export type ChatEvaluationCreateRequest = z.infer<typeof chatEvaluationCreateRequestSchema>;

export function fetchChatTasks(signal: AbortSignal): Promise<z.infer<typeof matraixChatTasksResponseSchema>> {
  return getJson(tasksEndpoint, matraixChatTasksResponseSchema, signal);
}

export function fetchChatEvaluations(
  page: number,
  signal: AbortSignal,
): Promise<z.infer<typeof chatEvaluationsResponseSchema>> {
  return getJson(
    `${evaluationsEndpoint}?page=${pageSchema.parse(page)}&page_size=20`,
    chatEvaluationsResponseSchema,
    signal,
  );
}

export function fetchChatEvaluation(
  evaluationId: string,
  signal: AbortSignal,
): Promise<ChatEvaluationDetail> {
  const id = identifierSchema.parse(evaluationId);
  return getJson(
    `${evaluationsEndpoint}/${encodeURIComponent(id)}`,
    chatEvaluationDetailSchema,
    signal,
  );
}

export function fetchChatEvaluationProgress(
  evaluationId: string,
  signal: AbortSignal,
): Promise<ParentProgress> {
  const id = identifierSchema.parse(evaluationId);
  return getJson(
    `${evaluationsEndpoint}/${encodeURIComponent(id)}/progress`,
    parentProgressSchema,
    signal,
  );
}

export function fetchChatTranscriptDelta(
  evaluationId: string,
  afterEventSequence: string,
  signal: AbortSignal,
): Promise<ChatTranscriptDelta> {
  const id = identifierSchema.parse(evaluationId);
  const cursor = eventSequenceSchema.parse(afterEventSequence);
  return getJson(
    `${evaluationsEndpoint}/${encodeURIComponent(id)}/transcript-delta?after_event_sequence=${encodeURIComponent(cursor)}`,
    chatTranscriptDeltaSchema,
    signal,
  );
}

export function mergeChatTranscriptDelta(
  detail: ChatEvaluationDetail,
  delta: ChatTranscriptDelta,
): ChatEvaluationDetail {
  if (delta.evaluation_id !== detail.id) {
    throw new Error("Transcript delta does not belong to the selected Chat evaluation.");
  }
  const trialIndexById = new Map(detail.trials.map((trial, index) => [trial.id, index]));
  const transcripts = detail.trials.map((trial) => [...trial.transcript]);
  for (const item of delta.items) {
    const trialIndex = trialIndexById.get(item.trial_id);
    if (trialIndex === undefined) {
      throw new Error(`Transcript delta references unknown Chat trial ${item.trial_id}.`);
    }
    const transcript = transcripts[trialIndex];
    if (transcript === undefined) {
      throw new Error(`Transcript state is missing Chat trial ${item.trial_id}.`);
    }
    const existing = transcript[item.message.position];
    if (existing !== undefined) {
      if (JSON.stringify(existing) !== JSON.stringify(item.message)) {
        throw new Error(
          `Transcript delta conflicts with immutable Chat message ${item.trial_id}:${item.message.position}.`,
        );
      }
      continue;
    }
    if (item.message.position !== transcript.length) {
      throw new Error(
        `Transcript delta is not contiguous for Chat trial ${item.trial_id}.`,
      );
    }
    transcript.push(item.message);
  }
  const trials = detail.trials.map((trial, index) => {
    const transcript = transcripts[index];
    if (transcript === undefined) {
      throw new Error(`Transcript state is missing Chat trial ${trial.id}.`);
    }
    return { ...trial, transcript };
  });
  return chatEvaluationDetailSchema.parse({
    ...detail,
    trials,
  });
}

export function fetchChatTrial(
  trialId: string,
  signal: AbortSignal,
): Promise<ChatTrial> {
  const id = identifierSchema.parse(trialId);
  return getJson(`${trialsEndpoint}/${encodeURIComponent(id)}`, chatTrialSchema, signal);
}

export async function fetchChatTrialTrajectory(
  trialId: string,
  expectedTrialSha256: string,
  signal: AbortSignal,
): Promise<ChatTrialAtifProjection> {
  const id = identifierSchema.parse(trialId);
  const trialSha256 = sha256DigestSchema.parse(expectedTrialSha256);
  const projection = await getJson(
    `${trialsEndpoint}/${encodeURIComponent(id)}/trajectory`,
    chatTrialAtifProjectionSchema,
    signal,
  );
  if (projection.trajectory.session_id !== id
    || projection.source_trial_sha256 !== trialSha256) {
    throw new Error("ATIF trajectory does not belong to the selected Chat trial");
  }
  return projection;
}

export function fetchChatReadiness(signal: AbortSignal): Promise<ChatReadiness> {
  return getJson(readinessEndpoint, chatReadinessSchema, signal);
}

export function createChatEvaluation(
  request: ChatEvaluationCreateRequest,
  signal: AbortSignal,
): Promise<ChatEvaluationDetail> {
  const body = chatEvaluationCreateRequestSchema.parse(request);
  return postJson(evaluationsEndpoint, body, chatEvaluationDetailSchema, signal);
}

export function retryChatEvaluation(
  evaluationId: string,
  signal: AbortSignal,
): Promise<ChatEvaluationDetail> {
  const id = identifierSchema.parse(evaluationId);
  return postJson(
    `${evaluationsEndpoint}/${encodeURIComponent(id)}/retry`,
    {},
    chatEvaluationDetailSchema,
    signal,
  );
}
