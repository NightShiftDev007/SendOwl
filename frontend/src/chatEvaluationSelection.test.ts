import { describe, expect, it } from "vitest";

import type { ChatTrial } from "./chatEvaluationContracts";
import { resolveChatTrialSelection } from "./chatEvaluationSelection";

const selectedId = "b9f503c2-0fa0-47d2-96b2-bec014440822";
const otherId = "2ce907de-4709-4eb6-b702-abac631607c7";
const queuedTrial = {
  id: selectedId,
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
  transcript: [],
  feedback: null,
  result: null,
  error: null,
} as ChatTrial;

describe("Chat trial selection", () => {
  it("does not auto-select the first trial", () => {
    expect(resolveChatTrialSelection([queuedTrial], null)).toEqual({ status: "idle" });
  });

  it("returns only an exact trial membership match", () => {
    expect(resolveChatTrialSelection([queuedTrial], selectedId)).toEqual({
      status: "selected",
      trial: queuedTrial,
    });
  });

  it("rejects a deep-linked trial outside the selected Evaluation without fallback", () => {
    expect(resolveChatTrialSelection([queuedTrial], otherId)).toEqual({
      status: "invalid",
      trialId: otherId,
    });
  });
});
