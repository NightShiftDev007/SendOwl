import { describe, expect, it } from "vitest";

import {
  createMediaArticlesEndpoint,
  createMediaTopicsEndpoint,
  mediaArticlesResponseSchema,
  mediaOverviewSchema,
  mediaTopicsResponseSchema,
} from "./mediaContracts";

const validArticle = {
  id: "02e985f8-82f9-4e89-aa26-34539874dfde",
  title: "企业发布季度经营数据",
  source_name: "Example News",
  published_at: "2026-08-12T04:30:00Z",
  excerpt: "报道摘录必须来自接口，且不能使用空字符串。",
  original_url: "https://example.com/articles/1",
  country_code: "CN",
  topic_id: "7a60965f-12b4-46be-b78b-61b39922059c",
  topic: "季度业绩",
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
