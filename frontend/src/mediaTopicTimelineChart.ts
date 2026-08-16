import type { MediaTopicTimelinePoint } from "./mediaContracts";

export interface MediaTopicTimelineChartData {
  readonly timestamps: readonly string[];
  readonly articleCounts: readonly number[];
  readonly salienceScores: readonly number[];
  readonly salienceRanks: readonly (number | null)[];
  readonly maximumArticleCount: number;
  readonly maximumSalienceScore: number;
}

function maximumOrZero(values: readonly number[]): number {
  return values.reduce((maximum, value) => Math.max(maximum, value), 0);
}

export function buildMediaTopicTimelineChartData(
  points: readonly MediaTopicTimelinePoint[],
): MediaTopicTimelineChartData {
  const timestamps = points.map((point) => point.window_start);
  const articleCounts = points.map((point) => point.article_count);
  const salienceScores = points.map((point) => point.salience_score);
  const salienceRanks = points.map((point) => point.salience_rank);

  return {
    timestamps,
    articleCounts,
    salienceScores,
    salienceRanks,
    maximumArticleCount: maximumOrZero(articleCounts),
    maximumSalienceScore: maximumOrZero(salienceScores),
  };
}
