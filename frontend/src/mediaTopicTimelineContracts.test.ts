import { describe, expect, it } from "vitest";

import {
  createMediaTopicTimelineEndpoint,
  mediaTopicTimelineResponseSchema,
} from "./mediaContracts";

const topicId = "5f1f94f9-7cbe-4aa9-aa71-bf4a1d00f4f4";

const validAggregateResponse = {
  topic_id: topicId,
  topic: "全球产业政策",
  selected_country: null,
  points: [
    {
      window_start: "2026-08-12T01:00:00Z",
      window_end: "2026-08-12T02:00:00Z",
      granularity: "hour",
      article_count: 18,
      salience_score: 9.75,
      salience_rank: null,
    },
  ],
  latest_countries: [
    {
      country_code: "CN",
      window_start: "2026-08-12T01:00:00Z",
      window_end: "2026-08-12T02:00:00Z",
      granularity: "hour",
      article_count: 7,
      salience_score: 4.25,
      salience_rank: 2,
    },
  ],
  generated_at: "2026-08-13T05:00:00Z",
  limitations: [
    "article_count is a country-indexed sum across country snapshots.",
    "Media salience is not causal inference.",
  ],
};

describe("media topic timeline contract", () => {
  it("accepts the strict aggregate response and its nullable aggregate rank", () => {
    expect(mediaTopicTimelineResponseSchema.safeParse(validAggregateResponse).success).toBe(true);
  });

  it("rejects undocumented response fields and empty limitations", () => {
    expect(
      mediaTopicTimelineResponseSchema.safeParse({
        ...validAggregateResponse,
        inferred_cause: "policy announcement",
      }).success,
    ).toBe(false);
    expect(
      mediaTopicTimelineResponseSchema.safeParse({
        ...validAggregateResponse,
        limitations: [],
      }).success,
    ).toBe(false);
  });

  it("requires a positive rank for every latest country snapshot", () => {
    expect(
      mediaTopicTimelineResponseSchema.safeParse({
        ...validAggregateResponse,
        latest_countries: [{ ...validAggregateResponse.latest_countries[0], salience_rank: 0 }],
      }).success,
    ).toBe(false);
  });

  it("builds the bounded aggregate and country endpoints without an empty country value", () => {
    expect(
      createMediaTopicTimelineEndpoint({ topicId, country: null, limit: 168 }),
    ).toBe(`/api/v2/media/topics/${topicId}/timeline?limit=168`);
    expect(
      createMediaTopicTimelineEndpoint({ topicId, country: "CN", limit: 168 }),
    ).toBe(`/api/v2/media/topics/${topicId}/timeline?limit=168&country=CN`);
  });
});
