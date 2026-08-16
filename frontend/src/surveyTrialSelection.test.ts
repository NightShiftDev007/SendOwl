import { describe, expect, it } from "vitest";

import type { SurveyTrial } from "./surveyContracts";
import { resolveSurveyTrialSelection } from "./surveyTrialSelection";

const trialId = "ff51bd82-385d-48ad-aa3c-9277dd927380";
const otherTrialId = "2ce907de-4709-4eb6-b702-abac631607c7";
const queuedTrial = {
  id: trialId,
  status: "queued",
  persona: {
    id: "d43de43d-c71e-4986-9b67-bd08ce096616",
    position: 0,
    persona_id: "persona-1",
    display_name: "Persona 1",
    profile_sha256: "a".repeat(64),
  },
  trial_sha256: "b".repeat(64),
  created_at: "2026-08-13T00:00:00Z",
  started_at: null,
  completed_at: null,
  result: null,
  error: null,
} as SurveyTrial;

describe("Survey trial selection", () => {
  it("does not auto-select the first trial", () => {
    expect(resolveSurveyTrialSelection([queuedTrial], null)).toEqual({ status: "idle" });
  });

  it("returns only an exact trial membership match", () => {
    expect(resolveSurveyTrialSelection([queuedTrial], trialId)).toEqual({
      status: "selected",
      trial: queuedTrial,
    });
  });

  it("rejects a trial outside the selected Survey experiment without fallback", () => {
    expect(resolveSurveyTrialSelection([queuedTrial], otherTrialId)).toEqual({
      status: "invalid",
      trialId: otherTrialId,
    });
  });
});
