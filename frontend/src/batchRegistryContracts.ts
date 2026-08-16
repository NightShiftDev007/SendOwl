import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const registriesEndpoint = "/api/v2/matraix/batch-registries";
const candidatesEndpoint = "/api/v2/matraix/batch-registry-candidates";
const nativeLaunchesEndpoint = "/api/v2/matraix/batch-launches";
const identifierSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const kindSchema = z.enum(["survey", "chat", "web", "linux"]);
const observedStatusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const titleSchema = z.string().trim().min(1).max(200).regex(/^[^\r\n]+$/u);
const sourceTitleSchema = z.string().trim().min(1).max(300).regex(/^[^\r\n]+$/u);
const modelNameSchema = z.string().trim().min(1).max(200).regex(/^[^\r\n]+$/u);

const countFieldsSchema = z.object({
  item_count: z.number().int().min(1).max(20),
  trial_count: z.number().int().positive().max(160),
  succeeded_trial_count: z.number().int().nonnegative().max(160),
  failed_trial_count: z.number().int().nonnegative().max(160),
}).strict();

const batchRegistrySummaryObjectSchema = z.object({
  id: identifierSchema,
  title: titleSchema,
  registry_state: z.literal("sealed"),
  execution_kind: z.literal("registry_only"),
  observed_trial_status: observedStatusSchema,
  observed_at: timestampSchema,
  created_at: timestampSchema,
  sealed_at: timestampSchema,
  registry_sha256: sha256DigestSchema,
}).merge(countFieldsSchema).strict();

function refineCounts(
  value: z.infer<typeof countFieldsSchema>,
  context: z.RefinementCtx,
): void {
  if (value.succeeded_trial_count + value.failed_trial_count > value.trial_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["failed_trial_count"],
      message: "Terminal observed trial counts cannot exceed trial_count",
    });
  }
}

export const matraixBatchRegistrySummarySchema = batchRegistrySummaryObjectSchema.superRefine(
  (registry, context) => {
    refineCounts(registry, context);
    refineObservedCounts(
      registry.observed_trial_status,
      registry.trial_count,
      registry.succeeded_trial_count,
      registry.failed_trial_count,
      "observed_trial_status",
      context,
    );
    if (Date.parse(registry.sealed_at) < Date.parse(registry.created_at)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["sealed_at"],
        message: "sealed_at must not precede created_at",
      });
    }
  },
);

const batchRegistryItemBaseSchema = z.object({
  parent_id: identifierSchema,
  parent_sha256: sha256DigestSchema,
  title: sourceTitleSchema,
  observed_status: observedStatusSchema,
  created_at: timestampSchema,
  trial_count: z.number().int().positive().max(8),
  succeeded_trial_count: z.number().int().nonnegative().max(8),
  failed_trial_count: z.number().int().nonnegative().max(8),
  model_name: modelNameSchema,
  parent_config_sha256: sha256DigestSchema,
  source_detail_path: z.string().trim().min(1).max(128).regex(/^\/api\/v2\/[A-Za-z0-9/_-]+$/u),
}).strict();

const surveyBatchRegistryItemSchema = batchRegistryItemBaseSchema.extend({
  position: z.number().int().min(0).max(19),
  kind: z.literal("survey"),
  version: z.literal("scenario-preference/v1"),
  prompt_schema_version: z.literal("matraix-survey-scenario-preference/v1"),
}).strict();

const chatBatchRegistryItemSchema = batchRegistryItemBaseSchema.extend({
  position: z.number().int().min(0).max(19),
  kind: z.literal("chat"),
  title: z.literal("Acme support: late order #4521"),
  version: z.literal("1.0.0"),
  prompt_schema_version: z.literal("matraix-chat-acme-support/v1"),
}).strict();

const webBatchRegistryItemSchema = batchRegistryItemBaseSchema.extend({
  position: z.number().int().min(0).max(19),
  kind: z.literal("web"),
  title: z.literal("Quote to save"),
  version: z.literal("1.0.0"),
  trial_count: z.number().int().positive().max(4),
  succeeded_trial_count: z.number().int().nonnegative().max(4),
  failed_trial_count: z.number().int().nonnegative().max(4),
  prompt_schema_version: z.literal("matraix-web-quotes-choice/v1"),
}).strict();

const linuxBatchRegistryItemSchema = batchRegistryItemBaseSchema.extend({
  position: z.number().int().min(0).max(19),
  kind: z.literal("linux"),
  title: z.literal("Note to CSV cleanup"),
  version: z.literal("1.0.0"),
  trial_count: z.literal(1),
  succeeded_trial_count: z.number().int().min(0).max(1),
  failed_trial_count: z.number().int().min(0).max(1),
  prompt_schema_version: z.literal("matraix-linux-note-to-csv/v1"),
}).strict();

const surveyBatchRegistryCandidateObjectSchema = batchRegistryItemBaseSchema.extend({
  kind: z.literal("survey"),
  version: z.literal("scenario-preference/v1"),
  prompt_schema_version: z.literal("matraix-survey-scenario-preference/v1"),
}).strict();

const chatBatchRegistryCandidateObjectSchema = batchRegistryItemBaseSchema.extend({
  kind: z.literal("chat"),
  title: z.literal("Acme support: late order #4521"),
  version: z.literal("1.0.0"),
  prompt_schema_version: z.literal("matraix-chat-acme-support/v1"),
}).strict();

const webBatchRegistryCandidateObjectSchema = batchRegistryItemBaseSchema.extend({
  kind: z.literal("web"),
  title: z.literal("Quote to save"),
  version: z.literal("1.0.0"),
  trial_count: z.number().int().positive().max(4),
  succeeded_trial_count: z.number().int().nonnegative().max(4),
  failed_trial_count: z.number().int().nonnegative().max(4),
  prompt_schema_version: z.literal("matraix-web-quotes-choice/v1"),
}).strict();

const linuxBatchRegistryCandidateObjectSchema = batchRegistryItemBaseSchema.extend({
  kind: z.literal("linux"),
  title: z.literal("Note to CSV cleanup"),
  version: z.literal("1.0.0"),
  trial_count: z.literal(1),
  succeeded_trial_count: z.number().int().min(0).max(1),
  failed_trial_count: z.number().int().min(0).max(1),
  prompt_schema_version: z.literal("matraix-linux-note-to-csv/v1"),
}).strict();

function refineObservedCounts(
  status: z.infer<typeof observedStatusSchema>,
  trialCount: number,
  succeededCount: number,
  failedCount: number,
  statusField: "observed_status" | "observed_trial_status",
  context: z.RefinementCtx,
): void {
  const terminalCount = succeededCount + failedCount;
  const valid = status === "queued"
    ? terminalCount === 0
    : status === "running"
      ? terminalCount < trialCount
      : status === "succeeded"
        ? succeededCount === trialCount && failedCount === 0
        : terminalCount === trialCount && failedCount > 0;
  if (!valid) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: [statusField],
      message: "Observed status must be reproducible from exact trial counts",
    });
  }
}

function refineTypedSourcePath(
  item: {
    readonly kind: z.infer<typeof kindSchema>;
    readonly parent_id: string;
    readonly source_detail_path: string;
  },
  context: z.RefinementCtx,
): void {
  const expectedPath = item.kind === "survey"
    ? `/api/v2/matraix/survey-experiments/${item.parent_id}`
    : item.kind === "chat"
      ? `/api/v2/matraix/chat-evaluations/${item.parent_id}`
      : item.kind === "web"
        ? `/api/v2/matraix/web-evaluations/${item.parent_id}`
        : `/api/v2/matraix/linux-evaluations/${item.parent_id}`;
  if (item.source_detail_path !== expectedPath) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["source_detail_path"],
      message: "Source detail path must identify the exact typed parent run",
    });
  }
}

export const matraixBatchRegistryItemSchema = z.discriminatedUnion("kind", [
  surveyBatchRegistryItemSchema,
  chatBatchRegistryItemSchema,
  webBatchRegistryItemSchema,
  linuxBatchRegistryItemSchema,
]).superRefine((item, context) => {
  if (item.succeeded_trial_count + item.failed_trial_count > item.trial_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["failed_trial_count"],
      message: "Terminal observed trial counts cannot exceed trial_count",
    });
  }
  refineObservedCounts(
    item.observed_status,
    item.trial_count,
    item.succeeded_trial_count,
    item.failed_trial_count,
    "observed_status",
    context,
  );
  refineTypedSourcePath(item, context);
});

export const matraixBatchRegistryCandidateSchema = z.discriminatedUnion("kind", [
  surveyBatchRegistryCandidateObjectSchema,
  chatBatchRegistryCandidateObjectSchema,
  webBatchRegistryCandidateObjectSchema,
  linuxBatchRegistryCandidateObjectSchema,
]).superRefine((candidate, context) => {
  if (candidate.succeeded_trial_count + candidate.failed_trial_count > candidate.trial_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["failed_trial_count"],
      message: "Terminal observed trial counts cannot exceed trial_count",
    });
  }
  refineObservedCounts(
    candidate.observed_status,
    candidate.trial_count,
    candidate.succeeded_trial_count,
    candidate.failed_trial_count,
    "observed_status",
    context,
  );
  refineTypedSourcePath(candidate, context);
});

export const matraixBatchRegistryDetailSchema = batchRegistrySummaryObjectSchema.extend({
  items: z.array(matraixBatchRegistryItemSchema).min(1).max(20),
}).strict().superRefine((registry, context) => {
  refineCounts(registry, context);
  refineObservedCounts(
    registry.observed_trial_status,
    registry.trial_count,
    registry.succeeded_trial_count,
    registry.failed_trial_count,
    "observed_trial_status",
    context,
  );
  if (Date.parse(registry.sealed_at) < Date.parse(registry.created_at)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["sealed_at"],
      message: "sealed_at must not precede created_at",
    });
  }
  if (registry.items.length !== registry.item_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Detail items must equal item_count",
    });
  }
  if (!registry.items.every((item, index) => item.position === index)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Batch items must follow contiguous frozen positions",
    });
  }
  const parentKeys = registry.items.map((item) => `${item.kind}:${item.parent_id}`);
  if (new Set(parentKeys).size !== parentKeys.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "A typed parent run may appear only once",
    });
  }
  const trialCount = registry.items.reduce((total, item) => total + item.trial_count, 0);
  const succeededCount = registry.items.reduce(
    (total, item) => total + item.succeeded_trial_count,
    0,
  );
  const failedCount = registry.items.reduce(
    (total, item) => total + item.failed_trial_count,
    0,
  );
  if (
    trialCount !== registry.trial_count
    || succeededCount !== registry.succeeded_trial_count
    || failedCount !== registry.failed_trial_count
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Summary observed counts must be exactly reproducible from items",
    });
  }
  const allQueued = registry.items.every((item) => item.observed_status === "queued");
  const allSucceeded = registry.items.every((item) => item.observed_status === "succeeded");
  const allTerminal = registry.items.every(
    (item) => item.observed_status === "succeeded" || item.observed_status === "failed",
  );
  const expectedStatus: z.infer<typeof observedStatusSchema> = allQueued
    ? "queued"
    : allSucceeded
      ? "succeeded"
      : allTerminal
        ? "failed"
        : "running";
  if (registry.observed_trial_status !== expectedStatus) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["observed_trial_status"],
      message: "Registry observed status must be reproducible from ordered items",
    });
  }
});

export const matraixBatchRegistriesResponseSchema = z.object({
  items: z.array(matraixBatchRegistrySummarySchema),
  observed_at: timestampSchema,
  page: z.number().int().positive(),
  page_size: z.number().int().min(1).max(100),
  total: z.number().int().nonnegative(),
}).strict().superRefine((response, context) => {
  if (response.items.length > response.page_size || response.items.length > response.total) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Batch directory page exceeds its declared bounds",
    });
  }
  if (response.items.some((item) => item.observed_at !== response.observed_at)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Registry summaries must share the response observation timestamp",
    });
  }
  if (response.items.some((item, index) => {
    const previous = response.items[index - 1];
    if (previous === undefined) return false;
    const timeOrder = Date.parse(previous.created_at) - Date.parse(item.created_at);
    if (timeOrder !== 0) return timeOrder < 0;
    return previous.id.localeCompare(item.id) > 0;
  })) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Registry summaries must follow created_at desc, id asc ordering",
    });
  }
});

export const matraixBatchRegistryCreateRequestSchema = z.object({
  title: titleSchema,
  items: z.array(z.object({
    kind: kindSchema,
    parent_id: identifierSchema,
  }).strict()).min(1).max(20),
}).strict().superRefine((request, context) => {
  const keys = request.items.map((item) => `${item.kind}:${item.parent_id}`);
  if (new Set(keys).size !== keys.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "A typed parent run may be registered only once",
    });
  }
});

const nativeSurveyLaunchItemSchema = z.object({
  kind: z.literal("survey"),
  scenario_id: identifierSchema,
  cohort_id: identifierSchema,
  alternative_id: identifierSchema,
}).strict();

const nativeChatLaunchItemSchema = z.object({
  kind: z.literal("chat"),
  cohort_id: identifierSchema,
  task_id: z.enum([
    "matraix/acme-support-order-4521",
    "matraix/acme-support-mcp-order-4521",
  ]),
  task_version: z.literal("1.0.0"),
}).strict();

export const matraixNativeBatchLaunchItemSchema = z.discriminatedUnion("kind", [
  nativeSurveyLaunchItemSchema,
  nativeChatLaunchItemSchema,
]);

export const matraixNativeBatchLaunchRequestSchema = z.object({
  title: titleSchema,
  items: z.array(matraixNativeBatchLaunchItemSchema).min(1).max(20),
}).strict().superRefine((request, context) => {
  const specs = request.items.map((item) => JSON.stringify(item));
  if (new Set(specs).size !== specs.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Native batch launch items must contain unique execution specs",
    });
  }
});

export const matraixNativeBatchLaunchResultSchema = z.object({
  launch_mode: z.literal("native_parent_enqueue"),
  registry: matraixBatchRegistryDetailSchema,
}).strict();

export const matraixBatchRegistriesQuerySchema = z.object({
  page: z.number().int().positive(),
  pageSize: z.number().int().min(1).max(100),
}).strict();

export const matraixBatchRegistryCandidatesResponseSchema = z.object({
  items: z.array(matraixBatchRegistryCandidateSchema),
  page: z.number().int().positive(),
  page_size: z.number().int().min(1).max(100),
  total: z.number().int().nonnegative(),
  observed_at: timestampSchema,
}).strict().superRefine((response, context) => {
  if (response.items.length > response.page_size || response.items.length > response.total) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Candidate page exceeds its declared bounds",
    });
  }
  if (response.items.some((item, index) => {
    const previous = response.items[index - 1];
    if (previous === undefined) return false;
    const timeOrder = Date.parse(previous.created_at) - Date.parse(item.created_at);
    if (timeOrder !== 0) return timeOrder < 0;
    if (previous.kind !== item.kind) return previous.kind.localeCompare(item.kind) > 0;
    return previous.parent_id.localeCompare(item.parent_id) > 0;
  })) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Candidates must follow created_at desc, kind asc, parent_id asc ordering",
    });
  }
});

export const matraixBatchRegistryCandidatesQuerySchema = z.object({
  page: z.number().int().positive(),
  pageSize: z.number().int().min(1).max(100),
  kind: kindSchema.nullable(),
}).strict();

export type MatraixBatchRegistryKind = z.infer<typeof kindSchema>;
export type MatraixBatchObservedStatus = z.infer<typeof observedStatusSchema>;
export type MatraixBatchRegistrySummary = z.infer<typeof matraixBatchRegistrySummarySchema>;
export type MatraixBatchRegistryItem = z.infer<typeof matraixBatchRegistryItemSchema>;
export type MatraixBatchRegistryDetail = z.infer<typeof matraixBatchRegistryDetailSchema>;
export type MatraixBatchRegistriesResponse = z.infer<typeof matraixBatchRegistriesResponseSchema>;
export type MatraixBatchRegistryCreateRequest = z.infer<typeof matraixBatchRegistryCreateRequestSchema>;
export type MatraixBatchRegistryCandidate = z.infer<typeof matraixBatchRegistryCandidateSchema>;
export type MatraixBatchRegistryCandidatesResponse = z.infer<typeof matraixBatchRegistryCandidatesResponseSchema>;
export type MatraixNativeBatchLaunchItem = z.infer<typeof matraixNativeBatchLaunchItemSchema>;
export type MatraixNativeBatchLaunchRequest = z.infer<typeof matraixNativeBatchLaunchRequestSchema>;
export type MatraixNativeBatchLaunchResult = z.infer<typeof matraixNativeBatchLaunchResultSchema>;

export interface MatraixBatchRegistriesQuery {
  readonly page: number;
  readonly pageSize: number;
}

export interface MatraixBatchRegistryCandidatesQuery {
  readonly page: number;
  readonly pageSize: number;
  readonly kind: MatraixBatchRegistryKind | null;
}

export function createBatchRegistriesEndpoint(query: MatraixBatchRegistriesQuery): string {
  const parsed = matraixBatchRegistriesQuerySchema.parse(query);
  const parameters = new URLSearchParams({
    page: String(parsed.page),
    page_size: String(parsed.pageSize),
  });
  return `${registriesEndpoint}?${parameters.toString()}`;
}

export function fetchBatchRegistries(
  query: MatraixBatchRegistriesQuery,
  signal: AbortSignal,
): Promise<MatraixBatchRegistriesResponse> {
  const parsed = matraixBatchRegistriesQuerySchema.parse(query);
  return getJson(
    createBatchRegistriesEndpoint(parsed),
    matraixBatchRegistriesResponseSchema,
    signal,
  )
    .then((response) => {
      if (response.page !== parsed.page || response.page_size !== parsed.pageSize) {
        throw new Error(
          `Batch Registry 分页响应与请求不一致：请求 page=${parsed.page}, page_size=${parsed.pageSize}，响应 page=${response.page}, page_size=${response.page_size}。`,
        );
      }
      return response;
    });
}

export function fetchBatchRegistry(
  registryId: string,
  signal: AbortSignal,
): Promise<MatraixBatchRegistryDetail> {
  const id = identifierSchema.parse(registryId);
  return getJson(
    `${registriesEndpoint}/${encodeURIComponent(id)}`,
    matraixBatchRegistryDetailSchema,
    signal,
  );
}

export function createBatchRegistryCandidatesEndpoint(
  query: MatraixBatchRegistryCandidatesQuery,
): string {
  const parsed = matraixBatchRegistryCandidatesQuerySchema.parse(query);
  const parameters = new URLSearchParams({
    page: String(parsed.page),
    page_size: String(parsed.pageSize),
  });
  if (parsed.kind !== null) parameters.set("kind", parsed.kind);
  return `${candidatesEndpoint}?${parameters.toString()}`;
}

export function fetchBatchRegistryCandidates(
  query: MatraixBatchRegistryCandidatesQuery,
  signal: AbortSignal,
): Promise<MatraixBatchRegistryCandidatesResponse> {
  const parsed = matraixBatchRegistryCandidatesQuerySchema.parse(query);
  return getJson(
    createBatchRegistryCandidatesEndpoint(parsed),
    matraixBatchRegistryCandidatesResponseSchema,
    signal,
  ).then((response) => {
    if (response.page !== parsed.page || response.page_size !== parsed.pageSize) {
      throw new Error(
        `Batch Registry 候选分页响应与请求不一致：请求 page=${parsed.page}, page_size=${parsed.pageSize}，响应 page=${response.page}, page_size=${response.page_size}。`,
      );
    }
    if (parsed.kind !== null && response.items.some((item) => item.kind !== parsed.kind)) {
      throw new Error(`Batch Registry 候选返回了不属于 kind=${parsed.kind} 的父运行。`);
    }
    return response;
  });
}

export function createBatchRegistry(
  request: MatraixBatchRegistryCreateRequest,
  signal: AbortSignal,
): Promise<MatraixBatchRegistryDetail> {
  return postJson(
    registriesEndpoint,
    matraixBatchRegistryCreateRequestSchema.parse(request),
    matraixBatchRegistryDetailSchema,
    signal,
  );
}

export function createNativeBatchLaunch(
  request: MatraixNativeBatchLaunchRequest,
  signal: AbortSignal,
): Promise<MatraixNativeBatchLaunchResult> {
  return postJson(
    nativeLaunchesEndpoint,
    matraixNativeBatchLaunchRequestSchema.parse(request),
    matraixNativeBatchLaunchResultSchema,
    signal,
  );
}
