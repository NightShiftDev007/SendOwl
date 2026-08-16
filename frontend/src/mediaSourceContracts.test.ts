import { describe, expect, it } from "vitest";

import {
  createMediaSourceEvidenceEndpoint,
  mediaSourceEvidenceResponseSchema,
  mediaSourceSummarySchema,
  mediaSourcesEndpoint,
  mediaSourcesResponseSchema,
} from "./mediaSourceContracts";

const validSource = {
  id: "6de0231e-cc0d-4ae6-a34c-20497d9736df",
  name: "Example News",
  country_code: "AE",
  homepage_url: "https://example.com/",
  media_type: "newspaper",
  language: "ar",
  status: "degraded",
  last_success_at: null,
};

describe("media source health contract", () => {
  it("accepts the exact source catalog projection and preserves API status keys", () => {
    const result = mediaSourcesResponseSchema.safeParse({
      items: [
        validSource,
        {
          ...validSource,
          id: "f0c97ad0-c00e-4858-a89b-f188d7ed0a69",
          name: "Second Source",
          status: "active",
          last_success_at: "2026-08-13T03:49:20.524066Z",
        },
      ],
      total: 2,
      status_counts: { active: 1, degraded: 1 },
    });

    expect(result.success).toBe(true);
    expect(result.data?.status_counts).toEqual({ active: 1, degraded: 1 });
    expect(mediaSourcesEndpoint).toBe("/api/v2/media/sources");
  });

  it("rejects undocumented fields and invalid source identity fields", () => {
    expect(
      mediaSourceSummarySchema.safeParse({
        ...validSource,
        inferred_health_score: 0.82,
      }).success,
    ).toBe(false);
    expect(
      mediaSourceSummarySchema.safeParse({ ...validSource, country_code: "ae" }).success,
    ).toBe(false);
    expect(
      mediaSourceSummarySchema.safeParse({ ...validSource, id: "source-1" }).success,
    ).toBe(false);
  });

  it("requires HTTP source links and timezone-aware success timestamps", () => {
    expect(
      mediaSourceSummarySchema.safeParse({
        ...validSource,
        homepage_url: "javascript:alert(1)",
      }).success,
    ).toBe(false);
    expect(
      mediaSourceSummarySchema.safeParse({
        ...validSource,
        last_success_at: "2026-08-13T03:49:20",
      }).success,
    ).toBe(false);
  });

  it("rejects negative, fractional, and non-numeric API status counts", () => {
    for (const invalidCount of [-1, 1.5, "1"]) {
      expect(
        mediaSourcesResponseSchema.safeParse({
          items: [validSource],
          total: 1,
          status_counts: { degraded: invalidCount },
        }).success,
      ).toBe(false);
    }
  });

  it("rejects undocumented source status and media type literals", () => {
    expect(
      mediaSourceSummarySchema.safeParse({ ...validSource, status: "healthy" }).success,
    ).toBe(false);
    expect(
      mediaSourceSummarySchema.safeParse({ ...validSource, media_type: "social" }).success,
    ).toBe(false);
    expect(
      mediaSourcesResponseSchema.safeParse({
        items: [validSource],
        total: 1,
        status_counts: { healthy: 1 },
      }).success,
    ).toBe(false);
  });

  it("validates source dossier evidence and its invariant bounds", () => {
    const response = {
      source: validSource,
      article_total: 1,
      first_published_at: "2026-08-01T00:00:00Z",
      latest_published_at: "2026-08-02T00:00:00Z",
      items: [{
        id: "e5033d24-9fbf-4a7a-a4fb-1cc684aeab77",
        title: "Verified report",
        source_name: validSource.name,
        published_at: "2026-08-02T00:00:00Z",
        excerpt: "A bounded evidence excerpt.",
        original_url: "https://example.com/reports/1",
        country_code: "AE",
        topic_id: null,
        topic: "Regional policy",
        evidence_revision_sha256: "0".repeat(64),
      }],
      page: 1,
      page_size: 20,
      total: 1,
      observed_at: "2026-08-03T00:00:00Z",
    };

    expect(mediaSourceEvidenceResponseSchema.safeParse(response).success).toBe(true);
    expect(mediaSourceEvidenceResponseSchema.safeParse({ ...response, article_total: 2 }).success).toBe(false);
    expect(createMediaSourceEvidenceEndpoint(validSource.id, 1, 20)).toBe(
      `/api/v2/media/sources/${validSource.id}/evidence?page=1&page_size=20`,
    );
  });
});
