import { z } from "zod";

import { getJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const evidenceBundlesEndpoint = "/api/v2/evidence-bundles";
const identifierSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const singleLineTextSchema = z.string().trim().min(1).max(300).regex(/^[^\r\n]+$/u);
const httpUrlSchema = z
  .string()
  .url()
  .refine((value) => ["http:", "https:"].includes(new URL(value).protocol));

const evidenceBundleSummaryObjectSchema = z
  .object({
    id: identifierSchema,
    bundle_sha256: sha256DigestSchema,
    title: singleLineTextSchema,
    world_model_id: identifierSchema,
    world_snapshot_id: identifierSchema,
    version: z.number().int().positive(),
    verification: z.literal("human_confirmed"),
    snapshot_sha256: sha256DigestSchema,
    item_count: z.number().int().min(1).max(50),
    created_at: timestampSchema,
  })
  .strict();

export const evidenceBundleSummarySchema = evidenceBundleSummaryObjectSchema
  .refine((bundle) => bundle.id === bundle.world_snapshot_id, {
    message: "Evidence bundle identity must equal its canonical world snapshot identity",
    path: ["world_snapshot_id"],
  });

export const evidenceBundleItemSchema = z
  .object({
    position: z.number().int().min(0).max(49),
    kind: z.literal("media_article"),
    article_id: identifierSchema,
    source_name: z.string().trim().min(1).max(300),
    original_url: httpUrlSchema,
    title: z.string().trim().min(1),
    published_at: timestampSchema,
    captured_at: timestampSchema,
    country_code: z.string().regex(/^[A-Z]{2}$/u).nullable(),
    excerpt: z.string().trim().min(1).max(280),
    captured_text_sha256: sha256DigestSchema,
  })
  .strict();

export const evidenceBundleDetailSchema = evidenceBundleSummaryObjectSchema
  .extend({
    items: z.array(evidenceBundleItemSchema).min(1).max(50),
  })
  .strict()
  .superRefine((bundle, context) => {
    if (bundle.id !== bundle.world_snapshot_id) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["world_snapshot_id"],
        message: "Evidence bundle identity must equal its canonical world snapshot identity",
      });
    }
    if (bundle.items.length !== bundle.item_count) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["items"],
        message: "Evidence bundle item count must match item_count",
      });
    }
    if (!bundle.items.every((item, index) => item.position === index)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["items"],
        message: "Evidence bundle item positions must be contiguous",
      });
    }
    const articleIds = bundle.items.map((item) => item.article_id);
    if (new Set(articleIds).size !== articleIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["items"],
        message: "Evidence bundle article identities must be unique",
      });
    }
  });

export const evidenceBundlesResponseSchema = z
  .object({
    items: z.array(evidenceBundleSummarySchema),
    total: z.number().int().nonnegative(),
  })
  .strict()
  .refine((response) => response.items.length === response.total, {
    message: "Evidence bundle response must expose its complete bounded directory",
    path: ["total"],
  });

export const evidenceBundleContentSchema = z
  .object({
    bundle_id: identifierSchema,
    bundle_sha256: sha256DigestSchema,
    article_id: identifierSchema,
    captured_text: z.string().min(1),
    captured_text_sha256: sha256DigestSchema,
  })
  .strict();

export type EvidenceBundleSummary = z.infer<typeof evidenceBundleSummarySchema>;
export type EvidenceBundleDetail = z.infer<typeof evidenceBundleDetailSchema>;
export type EvidenceBundleContent = z.infer<typeof evidenceBundleContentSchema>;
export type EvidenceBundlesResponse = z.infer<typeof evidenceBundlesResponseSchema>;

export function fetchEvidenceBundles(signal: AbortSignal): Promise<EvidenceBundlesResponse> {
  return getJson(evidenceBundlesEndpoint, evidenceBundlesResponseSchema, signal);
}

export function fetchEvidenceBundle(
  bundleId: string,
  signal: AbortSignal,
): Promise<EvidenceBundleDetail> {
  const normalizedBundleId = identifierSchema.parse(bundleId);
  return getJson(
    `${evidenceBundlesEndpoint}/${encodeURIComponent(normalizedBundleId)}`,
    evidenceBundleDetailSchema,
    signal,
  );
}

export function fetchEvidenceBundleContent(
  bundleId: string,
  articleId: string,
  signal: AbortSignal,
): Promise<EvidenceBundleContent> {
  const normalizedBundleId = identifierSchema.parse(bundleId);
  const normalizedArticleId = identifierSchema.parse(articleId);
  return getJson(
    `${evidenceBundlesEndpoint}/${encodeURIComponent(normalizedBundleId)}/items/${encodeURIComponent(normalizedArticleId)}/content`,
    evidenceBundleContentSchema,
    signal,
  );
}
