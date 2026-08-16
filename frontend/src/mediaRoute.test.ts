import { describe, expect, it } from "vitest";

import { createMediaHash, resolveMediaRoute } from "./mediaRoute";

const topicId = "693f538f-527c-428a-8dfe-97c3b0ad2907";
const sourceId = "c5373c9d-febf-4a28-abf2-90f5a92b1289";

describe("media route contract", () => {
  it("resolves the empty workspace without selecting a topic", () => {
    expect(resolveMediaRoute("")).toEqual({
      status: "resolved",
      route: { topicId: null, sourceId: null, lens: "articles", country: null },
    });
  });

  it("resolves a strict Topic Observatory deep link", () => {
    expect(resolveMediaRoute(`topic_id=${topicId}&lens=topic&country=CN`)).toEqual({
      status: "resolved",
      route: { topicId, sourceId: null, lens: "topic", country: "CN" },
    });
  });

  it("resolves the media source health lens", () => {
    expect(resolveMediaRoute("lens=sources")).toEqual({
      status: "resolved",
      route: { topicId: null, sourceId: null, lens: "sources", country: null },
    });
  });

  it("resolves a source dossier only from the sources lens", () => {
    expect(resolveMediaRoute(`lens=sources&source_id=${sourceId}`)).toEqual({
      status: "resolved",
      route: { topicId: null, sourceId, lens: "sources", country: null },
    });
  });

  it.each([
    "unknown=true",
    `topic_id=${topicId}&topic_id=${topicId}`,
    "topic_id=broken&lens=topic",
    `topic_id=${topicId}&lens=timeline`,
    `topic_id=${topicId}&lens=topic&country=cn`,
    `topic_id=${topicId}&lens=topic&country=CHN`,
    `source_id=${sourceId}`,
    `lens=articles&source_id=${sourceId}`,
    `lens=sources&source_id=${sourceId}&source_id=${sourceId}`,
    "lens=sources&source_id=broken",
    `lens=sources&topic_id=${topicId}`,
    "lens=sources&country=CN",
  ])("rejects invalid or ambiguous query %s", (query) => {
    expect(resolveMediaRoute(query).status).toBe("invalid");
  });

  it("serializes a stable topic-first deep link", () => {
    expect(createMediaHash({ topicId, sourceId: null, lens: "topic", country: "CN" })).toBe(
      `#/media?topic_id=${topicId}&lens=topic&country=CN`,
    );
    expect(createMediaHash({ topicId: null, sourceId: null, lens: "articles", country: null })).toBe("#/media");
    expect(createMediaHash({ topicId: null, sourceId: null, lens: "sources", country: null })).toBe(
      "#/media?lens=sources",
    );
    expect(createMediaHash({ topicId: null, sourceId, lens: "sources", country: null })).toBe(
      `#/media?lens=sources&source_id=${sourceId}`,
    );
  });
});
