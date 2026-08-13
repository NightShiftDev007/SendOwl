import { describe, expect, it } from "vitest";

import { createRunStudioHash, resolveRunStudioRoute } from "./runStudioRoute";

const experimentId = "2ce907de-4709-4eb6-b702-abac631607c7";
const trialId = "89ec5132-8273-4dd0-98d0-f2caeb2fd3fe";
const cohortId = "ff51bd82-385d-48ad-aa3c-9277dd927380";
const scenarioId = "af9b38d8-f040-4284-a1f5-b3e7ecf18066";

describe("Run Studio route contract", () => {
  it("defaults an empty query to platform smoke", () => {
    expect(resolveRunStudioRoute("")).toEqual({
      status: "resolved",
      route: {
        mode: "platform",
        cohortId: null,
        scenarioId: null,
        experimentId: null,
        trialId: null,
        panel: null,
      },
    });
  });

  it("parses a strict semantic experiment deep link", () => {
    expect(resolveRunStudioRoute(
      `mode=semantic&cohort_id=${cohortId}&scenario_id=${scenarioId}&experiment_id=${experimentId}&trial_id=${trialId}&panel=timeline`,
    )).toEqual({
      status: "resolved",
      route: {
        mode: "semantic",
        cohortId,
        scenarioId,
        experimentId,
        trialId,
        panel: "timeline",
      },
    });
  });

  it.each([
    "mode=semantic&surprise=true",
    "mode=semantic&mode=platform",
    "mode=semantic&experiment_id=not-a-uuid",
    `mode=semantic&trial_id=${trialId}`,
    `mode=platform&experiment_id=${experimentId}`,
    `mode=platform&cohort_id=${cohortId}`,
    `mode=platform&scenario_id=${scenarioId}`,
    "mode=semantic&panel=report",
  ])("rejects invalid or ambiguous query %s", (query) => {
    expect(resolveRunStudioRoute(query).status).toBe("invalid");
  });

  it("serializes parameters in one stable order", () => {
    expect(createRunStudioHash({
      mode: "semantic",
      cohortId,
      scenarioId,
      experimentId,
      trialId,
      panel: "metrics",
    })).toBe(
      `#/runs?mode=semantic&cohort_id=${cohortId}&scenario_id=${scenarioId}&experiment_id=${experimentId}&trial_id=${trialId}&panel=metrics`,
    );
  });

  it("refuses to serialize orphan or cross-mode selections", () => {
    expect(() => createRunStudioHash({
      mode: "semantic",
      cohortId: null,
      scenarioId: null,
      experimentId: null,
      trialId,
      panel: "timeline",
    })).toThrow("parent experiment");
    expect(() => createRunStudioHash({
      mode: "platform",
      cohortId: null,
      scenarioId: null,
      experimentId,
      trialId: null,
      panel: null,
    })).toThrow("Platform mode");
  });
});
