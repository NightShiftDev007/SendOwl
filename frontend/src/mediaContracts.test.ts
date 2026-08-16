import { describe, expect, it } from "vitest";

import {
  createMediaArticlesEndpoint,
  createMediaTopicsEndpoint,
  mediaArticlesResponseSchema,
  mediaFirstUtterancesResponseSchema,
  mediaOverviewSchema,
  mediaPropagationEdgeSchema,
  mediaPropagationResponseSchema,
  mediaTopicsResponseSchema,
} from "./mediaContracts";

const validArticle = {
  id: "02e985f8-82f9-4e89-aa26-34539874dfde",
  title: "行业发布季度经营数据",
  source_name: "Example News",
  published_at: "2026-08-12T04:30:00Z",
  excerpt: "报道摘录必须来自接口，且不能使用空字符串。",
  original_url: "https://example.com/articles/1",
  country_code: "CN",
  topic_id: "7a60965f-12b4-46be-b78b-61b39922059c",
  topic: "季度业绩",
  evidence_revision_sha256: "a".repeat(64),
};

describe("media overview contract", () => {
  it("accepts a complete overview payload", () => {
    const result = mediaOverviewSchema.safeParse({
      generated_at: "2026-08-12T05:00:00Z",
      source_count: 4,
      article_count: 21,
      topic_count: 3,
      country_nodes: [
        {
          country_code: "CN",
          lat: 35,
          lon: 104,
          article_count: 12,
          topic_id: "f6e32129-93cf-4200-a24e-268255664f83",
          topic: "产业政策",
        },
      ],
      hot_topics: [
        {
          topic_id: "f6e32129-93cf-4200-a24e-268255664f83",
          topic: "产业政策",
          article_count: 12,
        },
      ],
      latest_articles: [validArticle],
    });

    expect(result.success).toBe(true);
  });

  it("rejects nullable node topics instead of fabricating a display value", () => {
    const result = mediaOverviewSchema.safeParse({
      generated_at: "2026-08-12T05:00:00Z",
      source_count: 1,
      article_count: 1,
      topic_count: 0,
      country_nodes: [
        {
          country_code: "CN",
          lat: 35,
          lon: 104,
          article_count: 1,
          topic_id: null,
          topic: null,
        },
      ],
      hot_topics: [],
      latest_articles: [],
    });

    expect(result.success).toBe(false);
  });
});

describe("media first-utterance evidence contract", () => {
  const response = {
    topic_id: "7a60965f-12b4-46be-b78b-61b39922059c",
    topic: "产业政策",
    total: 1,
    generated_at: "2026-08-13T05:00:00Z",
    limitations: ["Model-assisted evidence discovery, not an authoritative first claim."],
    items: [
      {
        id: "e00ac0cf-7831-4e9c-837c-e77098ed57be",
        entity_id: "13458539-bdaf-4904-8186-b85a88b0db19",
        entity_name: "Example Minister",
        entity_type: "person",
        country_code: "CN",
        occurred_at: "2026-08-12T03:00:00Z",
        evidence_quote: "This exact quote is present in the source article.",
        confidence: "high",
        model_name: "qwen-example",
        prompt_version: "first-utterance/v1",
        source_created_at: "2026-08-12T03:01:00Z",
        article: validArticle,
      },
    ],
  };

  it("accepts evidence-bound observations without reasoning fields", () => {
    expect(mediaFirstUtterancesResponseSchema.safeParse(response).success).toBe(true);
  });

  it("rejects model reasoning and unsupported confidence", () => {
    const item = { ...response.items[0], reasoning: "hidden chain", confidence: "medium" };
    expect(
      mediaFirstUtterancesResponseSchema.safeParse({ ...response, items: [item] }).success,
    ).toBe(false);
  });
});

describe("media articles contract", () => {
  it("rejects unsafe original links", () => {
    const result = mediaArticlesResponseSchema.safeParse({
      items: [{ ...validArticle, original_url: "not-a-url" }],
      page: 1,
      page_size: 20,
      total: 1,
      facets: { countries: [], topics: [] },
    });

    expect(result.success).toBe(false);
  });

  it("rejects non-http URL schemes", () => {
    const result = mediaArticlesResponseSchema.safeParse({
      items: [{ ...validArticle, original_url: "javascript:alert(1)" }],
      page: 1,
      page_size: 20,
      total: 1,
      facets: { countries: [], topics: [] },
    });

    expect(result.success).toBe(false);
  });

  it("encodes all supported query parameters", () => {
    const endpoint = createMediaArticlesEndpoint({
      q: "跨境 并购",
      country: "US",
      topicId: "06b03ed6-f8be-4059-a781-97ef156d667d",
      page: 2,
      pageSize: 20,
    });
    const url = new URL(endpoint, "https://sandowl.test");

    expect(url.pathname).toBe("/api/v2/media/articles");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      page: "2",
      page_size: "20",
      q: "跨境 并购",
      country: "US",
      topic_id: "06b03ed6-f8be-4059-a781-97ef156d667d",
    });
  });

  it("rejects excerpts that exceed the public 280-character contract", () => {
    const result = mediaArticlesResponseSchema.safeParse({
      items: [{ ...validArticle, excerpt: "摘".repeat(281) }],
      page: 1,
      page_size: 20,
      total: 1,
      facets: { countries: [], topics: [] },
    });

    expect(result.success).toBe(false);
  });

  it("requires an exact lowercase SHA-256 evidence revision", () => {
    expect(
      mediaArticlesResponseSchema.safeParse({
        items: [{ ...validArticle, evidence_revision_sha256: "A".repeat(64) }],
        page: 1,
        page_size: 20,
        total: 1,
        facets: { countries: [], topics: [] },
      }).success,
    ).toBe(false);
    expect(
      mediaArticlesResponseSchema.safeParse({
        items: [{ ...validArticle, evidence_revision_sha256: "a".repeat(63) }],
        page: 1,
        page_size: 20,
        total: 1,
        facets: { countries: [], topics: [] },
      }).success,
    ).toBe(false);
  });
});

describe("media topics contract", () => {
  it("requires pagination metadata and builds a bounded endpoint", () => {
    const result = mediaTopicsResponseSchema.safeParse({
      items: [
        {
          id: "06b03ed6-f8be-4059-a781-97ef156d667d",
          topic: "资本市场",
          summary: null,
          category: "finance",
          status: "heating",
          article_count: 9,
          last_seen_at: "2026-08-12T05:00:00Z",
        },
      ],
      page: 2,
      page_size: 50,
      total: 91,
    });
    const endpoint = createMediaTopicsEndpoint(2, 50);
    const url = new URL(endpoint, "https://sandowl.test");

    expect(result.success).toBe(true);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      page: "2",
      page_size: "50",
    });
  });
});

describe("media propagation contract", () => {
  it("accepts only typed observed country edges", () => {
    const result = mediaPropagationResponseSchema.safeParse({
      generated_at: "2026-08-13T05:00:00Z",
      total: 1,
      items: [
        {
          id: "02e985f8-82f9-4e89-aa26-34539874dfde",
          topic_id: "7a60965f-12b4-46be-b78b-61b39922059c",
          topic: "跨境议题传播",
          status: "confirmed",
          confidence: "confirmed",
          origin_country_code: "CN",
          origin_source_name: "Example News",
          origin_at: "2026-08-13T01:00:00Z",
          origin_confidence: "high",
          detection_method: "media_time_fallback",
          edges: [
            {
              position: 0,
              from_country_code: "CN",
              to_country_code: "US",
              lag_hours: 2.5,
              first_media_name: "Follower Media",
              first_article_id: null,
              first_published_at: "2026-08-13T03:30:00Z",
              source_follower_id: "6fdbe5ad-5d85-4988-9dde-d2db144c110e",
              follower_source_id: "ac4ec737-88e8-4ebf-9d8a-f9f9a52fe919",
              observation_source: "structured_followers",
            },
          ],
        },
      ],
    });

    expect(result.success).toBe(true);
  });

  it("rejects structured edges without follower provenance", () => {
    const result = mediaPropagationEdgeSchema.safeParse({
      position: 0,
      from_country_code: "CN",
      to_country_code: "US",
      lag_hours: 1,
      first_media_name: "Follower Media",
      first_article_id: null,
      first_published_at: "2026-08-13T03:30:00Z",
      source_follower_id: null,
      follower_source_id: null,
      observation_source: "structured_followers",
    });

    expect(result.success).toBe(false);
  });
});
