import { describe, expect, it } from "vitest";

import {
  evidenceBundleDetailSchema,
  evidenceBundlesResponseSchema,
} from "./evidenceBundleContracts";

const bundleId = "2d4b4206-06f8-4b46-a13f-4a37f4f96d9f";
const modelId = "97e7d887-3c4c-4c1a-8462-bd05a709409f";
const articleId = "7f8a9691-360c-4aa8-b384-95b24475a4eb";
const digest = "a".repeat(64);

function validDetail(): Record<string, unknown> {
  return {
    id: bundleId,
    bundle_sha256: digest,
    title: "能源政策观察",
    world_model_id: modelId,
    world_snapshot_id: bundleId,
    version: 1,
    verification: "human_confirmed",
    snapshot_sha256: digest,
    item_count: 1,
    created_at: "2026-08-13T00:00:00Z",
    items: [
      {
        position: 0,
        kind: "media_article",
        article_id: articleId,
        source_name: "Example News",
        original_url: "https://example.com/article",
        title: "能源政策报道",
        published_at: "2026-08-12T00:00:00Z",
        captured_at: "2026-08-13T00:00:00Z",
        country_code: "CN",
        excerpt: "可核验的报道摘要。",
        captured_text_sha256: digest,
      },
    ],
  };
}

describe("Evidence Bundle contracts", () => {
  it("accepts a strict sealed snapshot projection", () => {
    expect(evidenceBundleDetailSchema.parse(validDetail()).id).toBe(bundleId);
  });

  it("rejects non-contiguous items and a detached bundle identity", () => {
    const invalid = validDetail();
    invalid.world_snapshot_id = "e62b6126-1a2a-43fd-8f63-fc63396a6de5";
    invalid.items = [{ ...(invalid.items as Record<string, unknown>[])[0], position: 1 }];
    expect(evidenceBundleDetailSchema.safeParse(invalid).success).toBe(false);
  });

  it("rejects a directory whose total is not its complete item count", () => {
    const detail = validDetail();
    const { items: _items, ...summary } = detail;
    expect(evidenceBundlesResponseSchema.safeParse({ items: [summary], total: 2 }).success).toBe(false);
  });
});
