import { describe, expect, it } from "vitest";

import {
  createResearchProjectHash,
  resolveResearchProjectRoute,
} from "./researchProjectRoute";

const worldModelId = "2ce907de-4709-4eb6-b702-abac631607c7";
const snapshotId = "ff51bd82-385d-48ad-aa3c-9277dd927380";

describe("Research Project route", () => {
  it("resolves an empty route and an exact WorldSnapshot handoff", () => {
    expect(resolveResearchProjectRoute("")).toEqual({
      status: "resolved",
      route: { worldModelId: null, snapshotId: null, graphId: null },
    });
    expect(resolveResearchProjectRoute(
      `world_model_id=${worldModelId}&snapshot_id=${snapshotId}`,
    )).toEqual({
      status: "resolved",
      route: { worldModelId, snapshotId, graphId: null },
    });
  });

  it.each([
    "unknown=true",
    `world_model_id=${worldModelId}`,
    `snapshot_id=${snapshotId}`,
    "world_model_id=broken&snapshot_id=broken",
    `world_model_id=${worldModelId}&world_model_id=${worldModelId}&snapshot_id=${snapshotId}`,
  ])("rejects an incomplete or unsafe handoff: %s", (query) => {
    expect(resolveResearchProjectRoute(query).status).toBe("invalid");
  });

  it("serializes only a complete frozen evidence identity", () => {
    expect(createResearchProjectHash({ worldModelId: null, snapshotId: null, graphId: null })).toBe("#/projects");
    expect(createResearchProjectHash({ worldModelId, snapshotId, graphId: null })).toBe(
      `#/projects?world_model_id=${worldModelId}&snapshot_id=${snapshotId}`,
    );
    expect(() => createResearchProjectHash({ worldModelId, snapshotId: null, graphId: null })).toThrow();
  });
});
