import { describe, expect, it } from "vitest";

import { resolveSectionFromHash } from "./App";
import { requireNavigationItem } from "./domain";

describe("hash route resolution", () => {
  it.each(["", "#", "#/overview", "#/media", "#/companies", "#/world", "#/decisions", "#/runs"])(
    "resolves the legal route %s",
    (hash) => {
      expect(resolveSectionFromHash(hash).status).toBe("resolved");
    },
  );

  it("returns a diagnosable error for a malformed hash instead of throwing", () => {
    expect(resolveSectionFromHash("#media")).toMatchObject({
      status: "invalid",
      hash: "#media",
    });
  });

  it("returns a diagnosable error for an unknown workspace", () => {
    expect(resolveSectionFromHash("#/not-a-workspace")).toMatchObject({
      status: "invalid",
      hash: "#/not-a-workspace",
    });
  });

  it("exposes the world model route as a runtime workspace", () => {
    expect(requireNavigationItem("world").state).toBe("available");
  });

  it("exposes the decision experiment route as a runtime workspace", () => {
    expect(requireNavigationItem("decisions").state).toBe("available");
  });

  it("exposes the OASIS platform-smoke route as a runtime workspace", () => {
    expect(requireNavigationItem("runs").state).toBe("available");
  });
});
