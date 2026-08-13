import { describe, expect, it } from "vitest";

import { resolveSectionFromHash } from "./App";
import { requireNavigationItem } from "./domain";

describe("hash route resolution", () => {
  it.each(["", "#", "#/overview", "#/threads", "#/media", "#/world", "#/decisions", "#/personas", "#/tasks", "#/runs", "#/reports"])(
    "resolves the legal route %s",
    (hash) => {
      expect(resolveSectionFromHash(hash).status).toBe("resolved");
    },
  );

  it("resolves a strict semantic Run Studio deep link", () => {
    expect(resolveSectionFromHash(
      "#/runs?mode=semantic&experiment_id=2ce907de-4709-4eb6-b702-abac631607c7",
    )).toMatchObject({
      status: "resolved",
      section: "runs",
      runStudioRoute: {
        mode: "semantic",
        experimentId: "2ce907de-4709-4eb6-b702-abac631607c7",
      },
    });
  });

  it("preserves a Persona World Cohort handoff", () => {
    expect(resolveSectionFromHash(
      "#/runs?mode=semantic&cohort_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    )).toMatchObject({
      status: "resolved",
      section: "runs",
      runStudioRoute: {
        mode: "semantic",
        cohortId: "ff51bd82-385d-48ad-aa3c-9277dd927380",
      },
    });
  });

  it("preserves a Decision Workspace Scenario handoff", () => {
    expect(resolveSectionFromHash(
      "#/runs?mode=semantic&scenario_id=af9b38d8-f040-4284-a1f5-b3e7ecf18066",
    )).toMatchObject({
      status: "resolved",
      section: "runs",
      runStudioRoute: {
        mode: "semantic",
        scenarioId: "af9b38d8-f040-4284-a1f5-b3e7ecf18066",
      },
    });
  });

  it("resolves persistent decision and report resource deep links", () => {
    const identity = "2ce907de-4709-4eb6-b702-abac631607c7";
    expect(resolveSectionFromHash(`#/threads?thread_id=${identity}`)).toMatchObject({
      status: "resolved",
      section: "threads",
      resourceId: identity,
    });
    expect(resolveSectionFromHash(`#/reports?experiment_id=${identity}`)).toMatchObject({
      status: "resolved",
      section: "reports",
      resourceId: identity,
    });
  });

  it("resolves the Survey Playground inside Task Gallery", () => {
    expect(resolveSectionFromHash("#/tasks?task=survey")).toMatchObject({
      status: "resolved",
      section: "tasks",
      resourceId: "survey",
    });
  });

  it.each([
    "#/runs?unknown=true",
    "#/runs?mode=semantic&experiment_id=broken",
    "#/media?mode=semantic",
    "#/threads?thread_id=broken",
    "#/reports?unknown=true",
    "#/tasks?task=harbor",
    "#/tasks?unknown=survey",
    "#/tasks?task=survey&task=survey",
  ])("rejects the invalid deep link %s", (hash) => {
    expect(resolveSectionFromHash(hash).status).toBe("invalid");
  });

  it("rejects the removed company workspace route", () => {
    expect(resolveSectionFromHash("#/companies").status).toBe("invalid");
  });

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

  it("exposes persistent decision tasks as a runtime workspace", () => {
    expect(requireNavigationItem("threads").state).toBe("available");
  });

  it("exposes the decision experiment route as a runtime workspace", () => {
    expect(requireNavigationItem("decisions").state).toBe("available");
  });

  it("exposes the OASIS platform-smoke route as a runtime workspace", () => {
    expect(requireNavigationItem("runs").state).toBe("available");
  });

  it("exposes Persona World as a runtime workspace", () => {
    expect(requireNavigationItem("personas").state).toBe("available");
  });

  it("exposes Task Gallery as a runtime workspace", () => {
    expect(requireNavigationItem("tasks").state).toBe("available");
  });

  it("exposes decision reports as a runtime workspace", () => {
    expect(requireNavigationItem("reports").state).toBe("available");
  });
});
