import { z } from "zod";

import { getJson } from "./apiClient";

const countryCodeSchema = z
  .string()
  .regex(/^[A-Z]{2}$/, "country_code must be an uppercase ISO 3166-1 alpha-2 code");
const topicIdSchema = z.string().uuid().nullable();
const isoTimestampSchema = z.string().datetime({ offset: true });
export const sha256DigestSchema = z.string().regex(/^[0-9a-f]{64}$/u);
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
    evidence_revision_sha256: sha256DigestSchema,
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

const mediaTopicSnapshotGranularitySchema = z.enum(["hour", "day", "week"]);

export const mediaTopicTimelinePointSchema = z
  .object({
    window_start: isoTimestampSchema,
    window_end: isoTimestampSchema,
    granularity: mediaTopicSnapshotGranularitySchema,
    article_count: z.number().int().nonnegative(),
    salience_score: z.number().finite().nonnegative(),
    salience_rank: z.number().int().positive().nullable(),
  })
  .strict();

export const mediaTopicLatestCountrySchema = z
  .object({
    country_code: countryCodeSchema,
    window_start: isoTimestampSchema,
    window_end: isoTimestampSchema,
    granularity: mediaTopicSnapshotGranularitySchema,
    article_count: z.number().int().nonnegative(),
    salience_score: z.number().finite().nonnegative(),
    salience_rank: z.number().int().positive(),
  })
  .strict();

export const mediaTopicTimelineResponseSchema = z
  .object({
    topic_id: z.string().uuid(),
    topic: z.string().trim().min(1),
    selected_country: countryCodeSchema.nullable(),
    points: z.array(mediaTopicTimelinePointSchema),
    latest_countries: z.array(mediaTopicLatestCountrySchema).max(12),
    generated_at: isoTimestampSchema,
    limitations: z.array(z.string().trim().min(1)).min(1),
  })
  .strict();

export const mediaFirstUtteranceObservationSchema = z
  .object({
    id: z.string().uuid(),
    entity_id: z.string().uuid(),
    entity_name: z.string().trim().min(1).max(200),
    entity_type: z.enum(["person", "thinktank", "intl_org", "gov_body"]),
    country_code: countryCodeSchema,
    occurred_at: isoTimestampSchema.nullable(),
    evidence_quote: z.string().trim().min(1).max(2000),
    confidence: z.literal("high"),
    model_name: z.string().trim().min(1).max(200),
    prompt_version: z.string().trim().min(1).max(100),
    source_created_at: isoTimestampSchema,
    article: mediaArticleSchema,
  })
  .strict();

export const mediaFirstUtterancesResponseSchema = z
  .object({
    topic_id: z.string().uuid(),
    topic: z.string().trim().min(1),
    items: z.array(mediaFirstUtteranceObservationSchema).max(100),
    total: z.number().int().nonnegative(),
    generated_at: isoTimestampSchema,
    limitations: z.array(z.string().trim().min(1)).min(1),
  })
  .strict()
  .superRefine((response, context) => {
    if (response.total < response.items.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "first-utterance total cannot be smaller than returned items",
      });
    }
  });

export const mediaPropagationEdgeSchema = z
  .object({
    position: z.number().int().nonnegative(),
    from_country_code: countryCodeSchema,
    to_country_code: countryCodeSchema,
    lag_hours: z.number().finite().nonnegative(),
    first_media_name: z.string().trim().min(1).nullable(),
    first_article_id: z.string().uuid().nullable(),
    first_published_at: isoTimestampSchema.nullable(),
    source_follower_id: z.string().uuid().nullable(),
    follower_source_id: z.string().uuid().nullable(),
    observation_source: z.enum(["legacy_projection", "structured_followers", "native_collection"]),
  })
  .strict()
  .superRefine((edge, context) => {
    if (
      edge.observation_source === "structured_followers"
      && (edge.source_follower_id === null || edge.follower_source_id === null)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "structured propagation edges require follower identities",
      });
    }
    if (edge.observation_source === "legacy_projection" && edge.source_follower_id !== null) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "legacy propagation edges cannot claim a structured follower id",
      });
    }
    if (
      edge.observation_source === "native_collection"
      && (edge.source_follower_id !== null || edge.follower_source_id === null)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "native collection edge source identity is incomplete",
      });
    }
  });

export const mediaPropagationEventSchema = z
  .object({
    id: z.string().uuid(),
    topic_id: z.string().uuid(),
    topic: z.string().trim().min(1),
    status: z.enum(["watching", "suspected", "confirmed", "dismissed", "revised", "archived"]),
    confidence: z.enum(["watching", "suspected", "confirmed"]),
    origin_country_code: countryCodeSchema,
    origin_source_name: z.string().trim().min(1).nullable(),
    origin_at: isoTimestampSchema,
    origin_confidence: z.enum(["high", "medium", "low"]),
    detection_method: z.string().trim().min(1),
    edges: z.array(mediaPropagationEdgeSchema),
  })
  .strict();

export const mediaPropagationResponseSchema = z
  .object({
    generated_at: isoTimestampSchema,
    items: z.array(mediaPropagationEventSchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export type MediaCountryNode = z.infer<typeof mediaCountryNodeSchema>;
export type MediaArticle = z.infer<typeof mediaArticleSchema>;
export type MediaOverview = z.infer<typeof mediaOverviewSchema>;
export type MediaArticlesResponse = z.infer<typeof mediaArticlesResponseSchema>;
export type MediaCountryFacet = z.infer<typeof countryFacetSchema>;
export type MediaTopicFacet = z.infer<typeof topicFacetSchema>;
export type MediaTopicSummary = z.infer<typeof mediaTopicSummarySchema>;
export type MediaTopicsResponse = z.infer<typeof mediaTopicsResponseSchema>;
export type MediaTopicTimelinePoint = z.infer<typeof mediaTopicTimelinePointSchema>;
export type MediaTopicLatestCountry = z.infer<typeof mediaTopicLatestCountrySchema>;
export type MediaTopicTimelineResponse = z.infer<typeof mediaTopicTimelineResponseSchema>;
export type MediaFirstUtteranceObservation = z.infer<
  typeof mediaFirstUtteranceObservationSchema
>;
export type MediaFirstUtterancesResponse = z.infer<
  typeof mediaFirstUtterancesResponseSchema
>;
export type MediaPropagationEvent = z.infer<typeof mediaPropagationEventSchema>;
export type MediaPropagationResponse = z.infer<typeof mediaPropagationResponseSchema>;

export interface MediaArticlesQuery {
  readonly q: string | null;
  readonly country: string | null;
  readonly topicId: string | null;
  readonly page: number;
  readonly pageSize: number;
}

export interface MediaTopicTimelineQuery {
  readonly topicId: string;
  readonly country: string | null;
  readonly limit: number;
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

export function createMediaTopicTimelineEndpoint(
  query: MediaTopicTimelineQuery,
): string {
  const validatedQuery = z
    .object({
      topicId: z.string().uuid(),
      country: countryCodeSchema.nullable(),
      limit: z.number().int().min(2).max(500),
    })
    .strict()
    .parse(query);
  const parameters = new URLSearchParams({ limit: String(validatedQuery.limit) });

  if (validatedQuery.country !== null) {
    parameters.set("country", validatedQuery.country);
  }

  return `/api/v2/media/topics/${validatedQuery.topicId}/timeline?${parameters.toString()}`;
}

export function fetchMediaOverview(signal: AbortSignal): Promise<MediaOverview> {
  return getJson(mediaOverviewEndpoint, mediaOverviewSchema, signal);
}

export function fetchMediaPropagation(signal: AbortSignal): Promise<MediaPropagationResponse> {
  return getJson("/api/v2/media/propagation?limit=20", mediaPropagationResponseSchema, signal);
}

export function fetchMediaArticles(
  query: MediaArticlesQuery,
  signal: AbortSignal,
): Promise<MediaArticlesResponse> {
  const endpoint = createMediaArticlesEndpoint(query);

  return getJson(endpoint, mediaArticlesResponseSchema, signal);
}

export function fetchMediaArticle(
  articleId: string,
  signal: AbortSignal,
): Promise<MediaArticle> {
  const validatedId = z.string().uuid().parse(articleId);
  return getJson(
    `/api/v2/media/articles/${encodeURIComponent(validatedId)}`,
    mediaArticleSchema,
    signal,
  );
}

export function fetchMediaTopics(
  page: number,
  pageSize: number,
  signal: AbortSignal,
): Promise<MediaTopicsResponse> {
  const endpoint = createMediaTopicsEndpoint(page, pageSize);

  return getJson(endpoint, mediaTopicsResponseSchema, signal);
}

export async function fetchMediaTopicTimeline(
  query: MediaTopicTimelineQuery,
  signal: AbortSignal,
): Promise<MediaTopicTimelineResponse> {
  const endpoint = createMediaTopicTimelineEndpoint(query);
  const response = await getJson(endpoint, mediaTopicTimelineResponseSchema, signal);

  if (response.topic_id !== query.topicId) {
    throw new Error(
      `议题时间线响应 topic_id 不匹配。requested=${query.topicId}; received=${response.topic_id}`,
    );
  }

  if (response.selected_country !== query.country) {
    throw new Error(
      `议题时间线响应国家切面不匹配。requested=${query.country ?? "aggregate"}; received=${response.selected_country ?? "aggregate"}`,
    );
  }

  return response;
}

export async function fetchMediaFirstUtterances(
  topicId: string,
  limit: number,
  signal: AbortSignal,
): Promise<MediaFirstUtterancesResponse> {
  const validated = z
    .object({ topicId: z.string().uuid(), limit: z.number().int().min(1).max(100) })
    .strict()
    .parse({ topicId, limit });
  const endpoint = `/api/v2/media/topics/${validated.topicId}/first-utterances?limit=${validated.limit}`;
  const response = await getJson(endpoint, mediaFirstUtterancesResponseSchema, signal);
  if (response.topic_id !== validated.topicId) {
    throw new Error(
      `首发证据响应 topic_id 不匹配。requested=${validated.topicId}; received=${response.topic_id}`,
    );
  }
  return response;
}
