import { describe, expect, it } from "vitest";

import { buildMediaMapData } from "./MediaWorldMap";
import type { MediaCountryNode } from "./mediaContracts";
import { mapNameOf, registerWorldMap } from "./worldMap";

function node(countryCode: string, articleCount: number): MediaCountryNode {
  return {
    country_code: countryCode,
    lat: 0,
    lon: 0,
    article_count: articleCount,
    topic_id: null,
    topic: "测试议题",
  };
}

describe("world map media projection", () => {
  it("maps real ISO country nodes to bundled atlas feature names", () => {
    expect(mapNameOf("CN")).toBe("China");
    expect(mapNameOf("us")).toBe("United States of America");
    expect(mapNameOf("XX")).toBeNull();
  });

  it("preserves media counts and excludes nodes absent from the atlas contract", () => {
    expect(buildMediaMapData([node("CN", 42), node("XX", 9)])).toEqual([
      {
        name: "China",
        value: 42,
        countryCode: "CN",
        topic: "测试议题",
      },
    ]);
  });

  it("removes the non-business polar geometry that stretches across the map", () => {
    const map = registerWorldMap();
    const names = map.features.map((featureItem) => featureItem.properties?.name);

    expect(names).not.toContain("Antarctica");
  });
});
