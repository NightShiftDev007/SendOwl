import { z } from "zod";

import { getJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const archiveEndpoint = "/api/v2/matraix/trials";
const identifierSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const statusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const kindSchema = z.enum(["survey", "chat", "web", "linux"]);
const nonEmptyTextSchema = z.string().trim().min(1);
const singleLineTextSchema = nonEmptyTextSchema.regex(/^[^\r\n]+$/u);
const identifierTextSchema = z.string()
  .trim()
  .min(1)
  .max(128)
  .regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u);

const archiveTaskBaseSchema = z.object({
  title: singleLineTextSchema.max(300),
});

const archivePersonaSchema = z.object({
  id: identifierSchema,
  position: z.number().int().min(0).max(99),
  persona_id: identifierTextSchema,
  display_name: singleLineTextSchema.max(200),
  profile_sha256: sha256DigestSchema,
}).strict();

const archiveErrorSchema = z.object({
  code: identifierTextSchema,
  message: nonEmptyTextSchema.max(4_000),
}).strict();

const archiveItemCommonSchema = z.object({
  id: identifierSchema,
  status: statusSchema,
  parent_id: identifierSchema,
  parent_sha256: sha256DigestSchema,
  trial_sha256: sha256DigestSchema,
  persona: archivePersonaSchema,
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  error: archiveErrorSchema.nullable(),
});

const surveyProvenanceSchema = z.object({
  runner_version: z.literal("1.0.0").nullable(),
  model_name: singleLineTextSchema.max(200),
  parent_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("matraix-survey-scenario-preference/v1"),
  answers_sha256: sha256DigestSchema.nullable(),
}).strict();

const chatProvenanceSchema = z.object({
  runner_version: z.literal("1.0.0").nullable(),
  model_name: singleLineTextSchema.max(200),
  parent_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("matraix-chat-acme-support/v1"),
  transcript_sha256: sha256DigestSchema.nullable(),
  feedback_sha256: sha256DigestSchema.nullable(),
  result_sha256: sha256DigestSchema.nullable(),
}).strict();

const webProvenanceSchema = z.object({
  runner_version: z.literal("1.0.0").nullable(),
  model_name: singleLineTextSchema.max(200),
  parent_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("matraix-web-quotes-choice/v1"),
  trace_sha256: sha256DigestSchema.nullable(),
  result_sha256: sha256DigestSchema.nullable(),
}).strict();

const linuxProvenanceSchema = z.object({
  runner_version: z.literal("1.0.0").nullable(),
  model_name: singleLineTextSchema.max(200),
  parent_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("matraix-linux-note-to-csv/v1"),
  artifact_sha256: sha256DigestSchema.nullable(),
  result_sha256: sha256DigestSchema.nullable(),
}).strict();

const surveyTrialArchiveItemObjectSchema = archiveItemCommonSchema.extend({
  kind: z.literal("survey"),
  task: archiveTaskBaseSchema.extend({
    version: z.literal("scenario-preference/v1"),
  }).strict(),
  provenance: surveyProvenanceSchema,
  source_detail_path: z.string(),
}).strict();

const chatTrialArchiveItemObjectSchema = archiveItemCommonSchema.extend({
  kind: z.literal("chat"),
  task: archiveTaskBaseSchema.extend({
    title: z.literal("Acme support: late order #4521"),
    version: z.literal("1.0.0"),
  }).strict(),
  provenance: chatProvenanceSchema,
  source_detail_path: z.string(),
}).strict();

const webTrialArchiveItemObjectSchema = archiveItemCommonSchema.extend({
  kind: z.literal("web"),
  task: archiveTaskBaseSchema.extend({
    title: z.literal("Quote to save"),
    version: z.literal("1.0.0"),
  }).strict(),
  provenance: webProvenanceSchema,
  source_detail_path: z.string(),
}).strict();

const linuxTrialArchiveItemObjectSchema = archiveItemCommonSchema.extend({
  kind: z.literal("linux"),
  task: archiveTaskBaseSchema.extend({
    title: z.literal("Note to CSV cleanup"),
    version: z.literal("1.0.0"),
  }).strict(),
  provenance: linuxProvenanceSchema,
  source_detail_path: z.string(),
}).strict();

type ArchiveStateFields = {
  readonly status: z.infer<typeof statusSchema>;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly error: z.infer<typeof archiveErrorSchema> | null;
};

function refineArchiveState(
  item: ArchiveStateFields,
  runnerVersion: string | null,
  outputHashes: readonly (string | null)[],
  context: z.RefinementCtx,
): void {
  const hasAllOutputs = outputHashes.every((value) => value !== null);
  const hasAnyOutput = outputHashes.some((value) => value !== null);
  if (
    item.started_at !== null
    && Date.parse(item.started_at) < Date.parse(item.created_at)
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["started_at"],
      message: "started_at must not precede created_at",
    });
  }
  if (
    item.completed_at !== null
    && (
      item.started_at === null
      || Date.parse(item.completed_at) < Date.parse(item.started_at)
    )
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["completed_at"],
      message: "completed_at requires and must not precede started_at",
    });
  }

  if (item.status === "queued") {
    if (
      item.started_at !== null
      || item.completed_at !== null
      || item.error !== null
      || runnerVersion !== null
      || hasAnyOutput
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Queued archive items cannot expose runtime or output fields",
      });
    }
    return;
  }

  if (item.status === "running") {
    if (
      item.started_at === null
      || item.completed_at !== null
      || item.error !== null
      || runnerVersion !== null
      || hasAnyOutput
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Running archive items require only started_at",
      });
    }
    return;
  }

  if (item.status === "succeeded") {
    if (
      item.started_at === null
      || item.completed_at === null
      || item.error !== null
      || runnerVersion === null
      || !hasAllOutputs
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Succeeded archive items require timestamps, runner and every output hash",
      });
    }
    return;
  }

  if (
    item.started_at === null
    || item.completed_at === null
    || item.error === null
    || runnerVersion !== null
    || hasAnyOutput
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Failed archive items require timestamps and error without output fields",
    });
  }
}

export const surveyTrialArchiveItemSchema = surveyTrialArchiveItemObjectSchema
  .superRefine((item, context) => {
    if (item.source_detail_path !== `/api/v2/matraix/survey-trials/${item.id}`) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["source_detail_path"],
        message: "Survey detail path must identify this exact trial",
      });
    }
    refineArchiveState(
      item,
      item.provenance.runner_version,
      [item.provenance.answers_sha256],
      context,
    );
  });

export const chatTrialArchiveItemSchema = chatTrialArchiveItemObjectSchema
  .superRefine((item, context) => {
    if (item.source_detail_path !== `/api/v2/matraix/chat-trials/${item.id}`) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["source_detail_path"],
        message: "Chat detail path must identify this exact trial",
      });
    }
    refineArchiveState(
      item,
      item.provenance.runner_version,
      [
        item.provenance.transcript_sha256,
        item.provenance.feedback_sha256,
        item.provenance.result_sha256,
      ],
      context,
    );
  });

export const webTrialArchiveItemSchema = webTrialArchiveItemObjectSchema
  .superRefine((item, context) => {
    if (item.source_detail_path !== `/api/v2/matraix/web-trials/${item.id}`) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["source_detail_path"],
        message: "Web detail path must identify this exact trial",
      });
    }
    refineArchiveState(
      item,
      item.provenance.runner_version,
      [item.provenance.trace_sha256, item.provenance.result_sha256],
      context,
    );
  });

export const linuxTrialArchiveItemSchema = linuxTrialArchiveItemObjectSchema
  .superRefine((item, context) => {
    if (item.source_detail_path !== `/api/v2/matraix/linux-trials/${item.id}`) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["source_detail_path"],
        message: "Linux detail path must identify this exact trial",
      });
    }
    refineArchiveState(
      item,
      item.provenance.runner_version,
      [item.provenance.artifact_sha256, item.provenance.result_sha256],
      context,
    );
  });

export const trialArchiveItemSchema = z.discriminatedUnion("kind", [
  surveyTrialArchiveItemObjectSchema,
  chatTrialArchiveItemObjectSchema,
  webTrialArchiveItemObjectSchema,
  linuxTrialArchiveItemObjectSchema,
]).superRefine((item, context) => {
  if (item.kind === "survey") {
    const result = surveyTrialArchiveItemSchema.safeParse(item);
    if (!result.success) {
      result.error.issues.forEach((issue) => context.addIssue(issue));
    }
    return;
  }
  const result = item.kind === "chat"
    ? chatTrialArchiveItemSchema.safeParse(item)
    : item.kind === "web"
      ? webTrialArchiveItemSchema.safeParse(item)
      : linuxTrialArchiveItemSchema.safeParse(item);
  if (!result.success) {
    result.error.issues.forEach((issue) => context.addIssue(issue));
  }
});

function compareArchiveItems(
  left: z.infer<typeof trialArchiveItemSchema>,
  right: z.infer<typeof trialArchiveItemSchema>,
): number {
  if (left.created_at !== right.created_at) {
    const timestampOrder = Date.parse(right.created_at) - Date.parse(left.created_at);
    if (timestampOrder !== 0) return timestampOrder;
  }
  if (left.kind !== right.kind) return left.kind.localeCompare(right.kind);
  return left.id.localeCompare(right.id);
}

export const trialArchiveResponseSchema = z.object({
  items: z.array(trialArchiveItemSchema),
  page: z.number().int().positive(),
  page_size: z.number().int().min(1).max(100),
  total: z.number().int().nonnegative(),
  statistics: z.object({
    total: z.number().int().nonnegative(),
    by_kind: z.object({
      survey: z.number().int().nonnegative(),
      chat: z.number().int().nonnegative(),
      web: z.number().int().nonnegative(),
      linux: z.number().int().nonnegative(),
    }).strict(),
    by_status: z.object({
      queued: z.number().int().nonnegative(),
      running: z.number().int().nonnegative(),
      succeeded: z.number().int().nonnegative(),
      failed: z.number().int().nonnegative(),
    }).strict(),
  }).strict(),
}).strict().superRefine((response, context) => {
  if (response.items.length > response.page_size) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Archive page cannot contain more items than page_size",
    });
  }
  if (response.total < response.items.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["total"],
      message: "Total cannot be smaller than the returned page",
    });
  }
  const kindTotal = response.statistics.by_kind.survey
    + response.statistics.by_kind.chat
    + response.statistics.by_kind.web
    + response.statistics.by_kind.linux;
  const statusTotal = response.statistics.by_status.queued
    + response.statistics.by_status.running
    + response.statistics.by_status.succeeded
    + response.statistics.by_status.failed;
  if (
    response.statistics.total !== response.total
    || kindTotal !== response.total
    || statusTotal !== response.total
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["statistics"],
      message: "Archive statistics must equal the filtered total",
    });
  }
  if (response.items.some((item, index) => {
    const previous = response.items[index - 1];
    return previous !== undefined && compareArchiveItems(previous, item) > 0;
  })) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["items"],
      message: "Archive items must follow created_at desc, kind asc, id asc ordering",
    });
  }
});

export const trialArchiveQuerySchema = z.object({
  page: z.number().int().positive(),
  pageSize: z.number().int().min(1).max(100),
  kind: kindSchema.nullable(),
  status: statusSchema.nullable(),
}).strict();

const trialIntegrityCheckSchema = z.object({
  name: identifierTextSchema,
  status: z.enum(["passed", "not_applicable"]),
  content_sha256: sha256DigestSchema.nullable(),
}).strict().superRefine((check, context) => {
  if (check.status === "not_applicable" && check.content_sha256 !== null) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["content_sha256"],
      message: "Not-applicable checks cannot expose a digest",
    });
  }
});

export const trialIntegrityVerificationSchema = z.object({
  kind: kindSchema,
  trial_id: identifierSchema,
  status: statusSchema,
  verification: z.literal("verified"),
  verified_at: timestampSchema,
  checks: z.array(trialIntegrityCheckSchema).min(4).max(6),
  limitations: z.array(singleLineTextSchema.max(300)).min(2).max(3),
}).strict().superRefine((verification, context) => {
  const expectedByKind = {
    survey: ["sealed_parent", "trial_address", "state_shape", "survey_answers"],
    chat: [
        "sealed_parent",
        "trial_address",
        "state_shape",
        "chat_transcript",
        "chat_feedback",
        "chat_result",
    ],
    web: ["sealed_parent", "trial_address", "state_shape", "web_trace", "web_result"],
    linux: [
      "sealed_parent",
      "trial_address",
      "state_shape",
      "linux_artifact",
      "linux_result",
    ],
  } as const;
  const expected = expectedByKind[verification.kind];
  if (verification.checks.some((check, index) => check.name !== expected[index])) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["checks"],
      message: "Integrity checks must use the fixed kind-specific order",
    });
  }
});

export type TrialArchiveKind = z.infer<typeof kindSchema>;
export type TrialArchiveStatus = z.infer<typeof statusSchema>;
export type TrialArchiveItem = z.infer<typeof trialArchiveItemSchema>;
export type TrialArchiveResponse = z.infer<typeof trialArchiveResponseSchema>;
export type TrialIntegrityVerification = z.infer<typeof trialIntegrityVerificationSchema>;

export interface TrialArchiveQuery {
  readonly page: number;
  readonly pageSize: number;
  readonly kind: TrialArchiveKind | null;
  readonly status: TrialArchiveStatus | null;
}

export function createTrialArchiveEndpoint(query: TrialArchiveQuery): string {
  const parsed = trialArchiveQuerySchema.parse(query);
  const parameters = new URLSearchParams({
    page: String(parsed.page),
    page_size: String(parsed.pageSize),
  });
  if (parsed.kind !== null) parameters.set("kind", parsed.kind);
  if (parsed.status !== null) parameters.set("status", parsed.status);
  return `${archiveEndpoint}?${parameters.toString()}`;
}

export function fetchTrialArchive(
  query: TrialArchiveQuery,
  signal: AbortSignal,
): Promise<TrialArchiveResponse> {
  const requested = trialArchiveQuerySchema.parse(query);
  return getJson(
    createTrialArchiveEndpoint(requested),
    trialArchiveResponseSchema,
    signal,
  ).then((response) => {
    if (response.page !== requested.page || response.page_size !== requested.pageSize) {
      throw new Error(
        `Trial Archive 分页响应与请求不一致：请求 page=${requested.page}, page_size=${requested.pageSize}，响应 page=${response.page}, page_size=${response.page_size}。`,
      );
    }
    if (
      requested.kind !== null
      && response.items.some((item) => item.kind !== requested.kind)
    ) {
      throw new Error(`Trial Archive 返回了不属于 kind=${requested.kind} 的记录。`);
    }
    if (
      requested.status !== null
      && response.items.some((item) => item.status !== requested.status)
    ) {
      throw new Error(`Trial Archive 返回了不属于 status=${requested.status} 的记录。`);
    }
    return response;
  });
}

export function fetchTrialIntegrityVerification(
  kind: TrialArchiveKind,
  trialId: string,
  signal: AbortSignal,
): Promise<TrialIntegrityVerification> {
  const parsedKind = kindSchema.parse(kind);
  const parsedTrialId = identifierSchema.parse(trialId);
  return getJson(
    `/api/v2/matraix/trials/${parsedKind}/${parsedTrialId}/verification`,
    trialIntegrityVerificationSchema,
    signal,
  ).then((response) => {
    if (response.kind !== parsedKind || response.trial_id !== parsedTrialId) {
      throw new Error("Trial 完整性核验响应不属于请求的 Trial。");
    }
    return response;
  });
}
