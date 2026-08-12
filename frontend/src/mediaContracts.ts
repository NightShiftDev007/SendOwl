import { z } from "zod";

import { getJson } from "./apiClient";

const countryCodeSchema = z
  .string()
  .regex(/^[A-Z]{2}$/, "country_code must be an uppercase ISO 3166-1 alpha-2 code");
const topicIdSchema = z.string().uuid().nullable();
const isoTimestampSchema = z.string().datetime({ offset: true });
const originalArticleUrlSchema = z
  .string()
  .url()
  .refine(
    (url) => url.startsWith("https://") || url.startsWith("http://"),
    "original_url must use http or https",
  );

export const mediaCountryNodeSchema = z
  .object({
    country_code: countryCodeSchema,
    lat: z.number().finite().min(-90).max(90),
    lon: z.number().finite().min(-180).max(180),
    article_count: z.number().int().nonnegative(),
    topic_id: topicIdSchema,
    topic: z.string().trim().min(1),
  })
  .strict();

export const mediaArticleSchema = z
  .object({
    id: z.string().uuid(),
    title: z.string().trim().min(1),
    source_name: z.string().trim().min(1),
    published_at: isoTimestampSchema,
    excerpt: z.string().trim().min(1).max(280),
    original_url: originalArticleUrlSchema,
    country_code: countryCodeSchema.nullable(),
    topic_id: topicIdSchema,
    topic: z.string().trim().min(1),
  })
  .strict();

const topicFacetSchema = z
  .object({
    topic_id: topicIdSchema,
    topic: z.string().trim().min(1),
    article_count: z.number().int().nonnegative(),
  })
  .strict();

const countryFacetSchema = z
  .object({
    country_code: countryCodeSchema,
    article_count: z.number().int().nonnegative(),
  })
  .strict();

export const mediaOverviewSchema = z
  .object({
    generated_at: isoTimestampSchema,
    source_count: z.number().int().nonnegative(),
    article_count: z.number().int().nonnegative(),
    topic_count: z.number().int().nonnegative(),
    country_nodes: z.array(mediaCountryNodeSchema),
    hot_topics: z.array(topicFacetSchema),
    latest_articles: z.array(mediaArticleSchema),
  })
  .strict();

export const mediaArticlesResponseSchema = z
  .object({
    items: z.array(mediaArticleSchema),
    page: z.number().int().positive(),
    page_size: z.number().int().min(1).max(100),
    total: z.number().int().nonnegative(),
    facets: z
      .object({
        countries: z.array(countryFacetSchema),
        topics: z.array(topicFacetSchema),
      })
      .strict(),
  })
  .strict();

export const mediaTopicSummarySchema = z
  .object({
    id: z.string().uuid(),
    topic: z.string().trim().min(1),
    summary: z.string().nullable(),
    category: z.string().nullable(),
    status: z.string().trim().min(1),
    article_count: z.number().int().nonnegative(),
    last_seen_at: isoTimestampSchema,
  })
  .strict();

export const mediaTopicsResponseSchema = z
  .object({
    items: z.array(mediaTopicSummarySchema),
    page: z.number().int().positive(),
    page_size: z.number().int().min(1).max(100),
    total: z.number().int().nonnegative(),
  })
  .strict();

export type MediaCountryNode = z.infer<typeof mediaCountryNodeSchema>;
export type MediaArticle = z.infer<typeof mediaArticleSchema>;
export type MediaOverview = z.infer<typeof mediaOverviewSchema>;
export type MediaArticlesResponse = z.infer<typeof mediaArticlesResponseSchema>;
export type MediaCountryFacet = z.infer<typeof countryFacetSchema>;
export type MediaTopicFacet = z.infer<typeof topicFacetSchema>;
export type MediaTopicsResponse = z.infer<typeof mediaTopicsResponseSchema>;

export interface MediaArticlesQuery {
  readonly q: string | null;
  readonly country: string | null;
  readonly topicId: string | null;
  readonly page: number;
  readonly pageSize: number;
}

const mediaOverviewEndpoint = "/api/v2/media/overview";

export function createMediaArticlesEndpoint(query: MediaArticlesQuery): string {
  const parameters = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
  });

  if (query.q !== null) {
    parameters.set("q", query.q);
  }

  if (query.country !== null) {
    parameters.set("country", query.country);
  }

  if (query.topicId !== null) {
    parameters.set("topic_id", query.topicId);
  }

  return `/api/v2/media/articles?${parameters.toString()}`;
}

export function createMediaTopicsEndpoint(page: number, pageSize: number): string {
  const parameters = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });

  return `/api/v2/media/topics?${parameters.toString()}`;
}

export function fetchMediaOverview(signal: AbortSignal): Promise<MediaOverview> {
  return getJson(mediaOverviewEndpoint, mediaOverviewSchema, signal);
}

export function fetchMediaArticles(
  query: MediaArticlesQuery,
  signal: AbortSignal,
): Promise<MediaArticlesResponse> {
  const endpoint = createMediaArticlesEndpoint(query);

  return getJson(endpoint, mediaArticlesResponseSchema, signal);
}

export function fetchMediaTopics(
  page: number,
  pageSize: number,
  signal: AbortSignal,
): Promise<MediaTopicsResponse> {
  const endpoint = createMediaTopicsEndpoint(page, pageSize);

  return getJson(endpoint, mediaTopicsResponseSchema, signal);
}
