import { describe, expect, it } from "vitest";

import type { MediaTopicTimelinePoint } from "./mediaContracts";
import { buildMediaTopicTimelineChartData } from "./mediaTopicTimelineChart";

describe("media topic timeline chart data", () => {
  it("projects article, salience, and rank series without mutating observations", () => {
    const points = [
      {
        window_start: "2026-08-12T01:00:00Z",
        window_end: "2026-08-12T02:00:00Z",
        granularity: "hour",
        article_count: 4,
        salience_score: 2.25,
        salience_rank: null,
      },
      {
        window_start: "2026-08-12T02:00:00Z",
        window_end: "2026-08-12T03:00:00Z",
        granularity: "hour",
        article_count: 11,
        salience_score: 8.5,
        salience_rank: 3,
      },
    ] as const satisfies readonly MediaTopicTimelinePoint[];
    const originalPoints = points.map((point) => ({ ...point }));

    expect(buildMediaTopicTimelineChartData(points)).toEqual({
      timestamps: ["2026-08-12T01:00:00Z", "2026-08-12T02:00:00Z"],
      articleCounts: [4, 11],
      salienceScores: [2.25, 8.5],
      salienceRanks: [null, 3],
      maximumArticleCount: 11,
      maximumSalienceScore: 8.5,
    });
    expect(points).toEqual(originalPoints);
  });

  it("returns explicit zero maxima for an empty API timeline", () => {
    expect(buildMediaTopicTimelineChartData([])).toEqual({
      timestamps: [],
      articleCounts: [],
      salienceScores: [],
      salienceRanks: [],
      maximumArticleCount: 0,
      maximumSalienceScore: 0,
    });
  });
});
