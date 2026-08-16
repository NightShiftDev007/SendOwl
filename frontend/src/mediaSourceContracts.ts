import { z } from "zod";

import { getJson } from "./apiClient";
import { mediaArticleSchema } from "./mediaContracts";

const countryCodeSchema = z
  .string()
  .regex(/^[A-Z]{2}$/u, "country_code must be an uppercase ISO 3166-1 alpha-2 code");
const isoTimestampSchema = z.string().datetime({ offset: true });
const mediaTypeSchema = z.enum(["newspaper", "agency", "broadcast", "online"]);
const sourceStatusSchema = z.enum(["active", "degraded", "failed", "disabled"]);
const httpUrlSchema = z
  .string()
  .url()
  .refine(
    (url) => url.startsWith("https://") || url.startsWith("http://"),
    "homepage_url must use http or https",
  );

export const mediaSourceSummarySchema = z
  .object({
    id: z.string().uuid(),
    name: z.string().trim().min(1).max(200),
    country_code: countryCodeSchema,
    homepage_url: httpUrlSchema,
    media_type: mediaTypeSchema,
    language: z.string().trim().min(1).max(10),
    status: sourceStatusSchema,
    last_success_at: isoTimestampSchema.nullable(),
  })
  .strict();

export const mediaSourcesResponseSchema = z
  .object({
    items: z.array(mediaSourceSummarySchema),
    total: z.number().int().nonnegative(),
    status_counts: z.record(sourceStatusSchema, z.number().int().nonnegative()),
  })
  .strict();

export type MediaSourceSummary = z.infer<typeof mediaSourceSummarySchema>;
export type MediaSourcesResponse = z.infer<typeof mediaSourcesResponseSchema>;

export const mediaSourceEvidenceResponseSchema = z
  .object({
    source: mediaSourceSummarySchema,
    article_total: z.number().int().nonnegative(),
    first_published_at: isoTimestampSchema.nullable(),
    latest_published_at: isoTimestampSchema.nullable(),
    items: z.array(mediaArticleSchema),
    page: z.number().int().positive(),
    page_size: z.number().int().min(1).max(100),
    total: z.number().int().nonnegative(),
    observed_at: isoTimestampSchema,
  })
  .strict()
  .superRefine((value, context) => {
    if (value.article_total !== value.total) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "article_total must equal total" });
    }
    if (value.items.length > value.page_size || value.items.length > value.total) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "items exceeds pagination bounds" });
    }
    if ((value.first_published_at === null) !== (value.latest_published_at === null)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "publication bounds must both be null or timestamps" });
    }
    if (
      value.first_published_at !== null
      && value.latest_published_at !== null
      && value.first_published_at > value.latest_published_at
    ) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "first_published_at exceeds latest_published_at" });
    }
  });

export type MediaSourceEvidenceResponse = z.infer<typeof mediaSourceEvidenceResponseSchema>;

export const mediaSourcesEndpoint = "/api/v2/media/sources";

export function createMediaSourceEvidenceEndpoint(sourceId: string, page: number, pageSize: number): string {
  const validated = z.object({ sourceId: z.string().uuid(), page: z.number().int().positive(), pageSize: z.number().int().min(1).max(100) }).strict().parse({ sourceId, page, pageSize });
  return `/api/v2/media/sources/${validated.sourceId}/evidence?page=${validated.page}&page_size=${validated.pageSize}`;
}

export function fetchMediaSources(signal: AbortSignal): Promise<MediaSourcesResponse> {
  return getJson(mediaSourcesEndpoint, mediaSourcesResponseSchema, signal);
}

export function fetchMediaSourceEvidence(sourceId: string, page: number, pageSize: number, signal: AbortSignal): Promise<MediaSourceEvidenceResponse> {
  return getJson(createMediaSourceEvidenceEndpoint(sourceId, page, pageSize), mediaSourceEvidenceResponseSchema, signal);
}
