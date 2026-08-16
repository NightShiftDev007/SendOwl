import { describe, expect, it } from "vitest";

import { createWorldHash, resolveWorldRoute } from "./worldRoute";

const modelId = "2ce907de-4709-4eb6-b702-abac631607c7";
const snapshotId = "ff51bd82-385d-48ad-aa3c-9277dd927380";

describe("World route", () => {
  it("resolves an empty route and a complete snapshot deep link", () => {
    expect(resolveWorldRoute("")).toEqual({
      status: "resolved",
      route: { worldModelId: null, snapshotId: null, evidenceId: null },
    });
    expect(resolveWorldRoute(`world_model_id=${modelId}&snapshot_id=${snapshotId}`)).toEqual({
      status: "resolved",
      route: { worldModelId: modelId, snapshotId, evidenceId: null },
    });
  });

  it.each([
    "unknown=true",
    `world_model_id=${modelId}&world_model_id=${modelId}`,
    "world_model_id=broken",
    "snapshot_id=broken",
    "evidence_id=broken",
    `snapshot_id=${snapshotId}`,
  ])("rejects an unsafe route: %s", (query) => {
    expect(resolveWorldRoute(query).status).toBe("invalid");
  });

  it("serializes only explicit World context", () => {
    expect(createWorldHash({ worldModelId: null, snapshotId: null, evidenceId: null })).toBe("#/world");
    expect(createWorldHash({ worldModelId: modelId, snapshotId, evidenceId: null })).toBe(
      `#/world?world_model_id=${modelId}&snapshot_id=${snapshotId}`,
    );
    expect(createWorldHash({ worldModelId: null, snapshotId: null, evidenceId: snapshotId })).toBe(
      `#/world?evidence_id=${snapshotId}`,
    );
    expect(() => createWorldHash({ worldModelId: null, snapshotId, evidenceId: null })).toThrow();
  });
});
