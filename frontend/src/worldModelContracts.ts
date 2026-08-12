import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import {
  evidenceContextSchema,
  sha256DigestSchema,
  type CompanyCoverageItem,
} from "./companyContracts";

const worldModelsEndpoint = "/api/v2/world-models";
const identifierSchema = z.string().uuid();
const isoTimestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const worldModelTitleSchema = nonEmptyTextSchema
  .max(300)
  .regex(/^[^\r\n]+$/u, "World model title must be a single line");
const snapshotCompanyNameSchema = nonEmptyTextSchema
  .max(300)
  .regex(/^[^\r\n]+$/u, "Snapshot company name must be a single line");
const httpUrlSchema = z
  .string()
  .url()
  .refine((value) => {
    const protocol = new URL(value).protocol;

    return protocol === "http:" || protocol === "https:";
  }, "Expected an HTTP or HTTPS URL");

export const snapshotSummarySchema = z
  .object({
    id: identifierSchema,
    version: z.number().int().positive(),
    company_name: snapshotCompanyNameSchema,
    evidence_count: z.number().int().min(1).max(50),
    snapshot_sha256: sha256DigestSchema,
    created_at: isoTimestampSchema,
  })
  .strict();

export const worldModelSummarySchema = z
  .object({
    id: identifierSchema,
    title: worldModelTitleSchema,
    company_id: identifierSchema,
    company_name: nonEmptyTextSchema,
    created_at: isoTimestampSchema,
    latest_snapshot: snapshotSummarySchema,
  })
  .strict();

export const worldModelsResponseSchema = z
  .object({
    items: z.array(worldModelSummarySchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const snapshotCompanySchema = z
  .object({
    id: identifierSchema,
    canonical_name: nonEmptyTextSchema,
    aliases: z.array(nonEmptyTextSchema),
  })
  .strict();

export const snapshotEvidenceSchema = z
  .object({
    article_id: identifierSchema,
    source_name: nonEmptyTextSchema,
    original_url: httpUrlSchema,
    title: nonEmptyTextSchema,
    published_at: isoTimestampSchema,
    captured_at: isoTimestampSchema,
    country_code: z.string().regex(/^[A-Z]{2}$/u).nullable(),
    excerpt: nonEmptyTextSchema.max(280),
    captured_text_sha256: sha256DigestSchema,
    matched_aliases: z.array(nonEmptyTextSchema).min(1),
    evidence_contexts: z.array(evidenceContextSchema).min(1),
  })
  .strict();

export const snapshotDetailSchema = z
  .object({
    id: identifierSchema,
    world_model_id: identifierSchema,
    version: z.number().int().positive(),
    verification: z.literal("human_confirmed"),
    snapshot_sha256: sha256DigestSchema,
    created_at: isoTimestampSchema,
    company: snapshotCompanySchema,
    evidence: z.array(snapshotEvidenceSchema).min(1).max(50),
  })
  .strict();

export const worldModelDetailSchema = z
  .object({
    id: identifierSchema,
    title: worldModelTitleSchema,
    company_id: identifierSchema,
    created_at: isoTimestampSchema,
    snapshots: z.array(snapshotSummarySchema).min(1),
    latest_snapshot: snapshotDetailSchema,
  })
  .strict()
  .superRefine((worldModel, context) => {
    if (worldModel.latest_snapshot.world_model_id !== worldModel.id) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_snapshot", "world_model_id"],
        message: "latest_snapshot must belong to the enclosing world model",
      });
    }

    if (worldModel.company_id !== worldModel.latest_snapshot.company.id) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_snapshot", "company", "id"],
        message: "snapshot company must match the enclosing world model",
      });
    }

    const matchingSummaries = worldModel.snapshots.filter(
      (snapshot) => snapshot.id === worldModel.latest_snapshot.id,
    );
    const latestSummary = matchingSummaries[0];

    if (
      matchingSummaries.length !== 1
      || latestSummary === undefined
      || latestSummary.version !== worldModel.latest_snapshot.version
      || latestSummary.company_name !== worldModel.latest_snapshot.company.canonical_name
      || latestSummary.snapshot_sha256 !== worldModel.latest_snapshot.snapshot_sha256
      || latestSummary.evidence_count !== worldModel.latest_snapshot.evidence.length
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_snapshot"],
        message: "latest_snapshot must match its snapshot summary",
      });
    }

    const highestVersion = Math.max(
      ...worldModel.snapshots.map((snapshot) => snapshot.version),
    );

    if (worldModel.latest_snapshot.version !== highestVersion) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_snapshot", "version"],
        message: "latest_snapshot must be the highest snapshot version",
      });
    }
  });

export const worldModelEvidenceSelectionSchema = z
  .object({
    article_id: identifierSchema,
    evidence_revision_sha256: sha256DigestSchema,
  })
  .strict();

export const worldModelCreateRequestSchema = z
  .object({
    title: worldModelTitleSchema,
    company_id: identifierSchema,
    evidence: z.array(worldModelEvidenceSelectionSchema).min(1).max(50),
    verification: z.literal("human_confirmed"),
  })
  .strict()
  .superRefine((request, context) => {
    const articleIds = request.evidence.map((selection) => selection.article_id);
    const uniqueArticleIds = new Set(articleIds);

    if (uniqueArticleIds.size !== articleIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["evidence"],
        message: "evidence article_id values must not contain duplicates",
      });
    }
  });

export type SnapshotSummary = z.infer<typeof snapshotSummarySchema>;
export type WorldModelSummary = z.infer<typeof worldModelSummarySchema>;
export type WorldModelsResponse = z.infer<typeof worldModelsResponseSchema>;
export type SnapshotCompany = z.infer<typeof snapshotCompanySchema>;
export type SnapshotEvidence = z.infer<typeof snapshotEvidenceSchema>;
export type SnapshotDetail = z.infer<typeof snapshotDetailSchema>;
export type WorldModelDetail = z.infer<typeof worldModelDetailSchema>;
export type WorldModelEvidenceSelection = z.infer<typeof worldModelEvidenceSelectionSchema>;
export type WorldModelCreateRequest = z.infer<typeof worldModelCreateRequestSchema>;

export function buildWorldModelCreateRequest(
  title: string,
  companyId: string,
  selectedArticleIds: readonly string[],
  coverageItems: readonly CompanyCoverageItem[],
): WorldModelCreateRequest {
  const coverageByArticleId = new Map<string, CompanyCoverageItem>();

  for (const item of coverageItems) {
    const articleId = item.article.id;

    if (coverageByArticleId.has(articleId)) {
      throw new Error(
        `无法冻结世界模型：当前企业证据响应重复包含报道 ${articleId}，无法确定用户阅读的正文版本。请刷新候选。`,
      );
    }

    coverageByArticleId.set(articleId, item);
  }

  const evidence = selectedArticleIds.map((articleId) => {
    const coverageItem = coverageByArticleId.get(articleId);

    if (coverageItem === undefined) {
      throw new Error(
        `无法冻结世界模型：所选报道 ${articleId} 不在当前已加载的企业证据响应中。请刷新候选并重新阅读确认。`,
      );
    }

    return {
      article_id: articleId,
      evidence_revision_sha256: coverageItem.evidence_revision_sha256,
    };
  });

  return worldModelCreateRequestSchema.parse({
    title,
    company_id: companyId,
    evidence,
    verification: "human_confirmed",
  });
}

export function createWorldModelDetailEndpoint(worldModelId: string): string {
  return `${worldModelsEndpoint}/${encodeURIComponent(worldModelId)}`;
}

export function fetchWorldModels(signal: AbortSignal): Promise<WorldModelsResponse> {
  return getJson(worldModelsEndpoint, worldModelsResponseSchema, signal);
}

export function fetchWorldModelDetail(
  worldModelId: string,
  signal: AbortSignal,
): Promise<WorldModelDetail> {
  return getJson(
    createWorldModelDetailEndpoint(worldModelId),
    worldModelDetailSchema,
    signal,
  );
}

export function createWorldModel(
  request: WorldModelCreateRequest,
  signal: AbortSignal,
): Promise<WorldModelDetail> {
  const validatedRequest = worldModelCreateRequestSchema.parse(request);

  return postJson(worldModelsEndpoint, validatedRequest, worldModelDetailSchema, signal);
}
