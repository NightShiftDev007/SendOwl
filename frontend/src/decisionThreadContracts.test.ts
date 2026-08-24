import { describe, expect, it } from "vitest";

import {
  decisionThreadContextRequestSchema,
  decisionThreadDraftCreateRequestSchema,
  decisionThreadDetailSchema,
} from "./decisionThreadContracts";

const ids = {
  thread: "10000000-0000-4000-8000-000000000001",
  revision: "10000000-0000-4000-8000-000000000002",
  model: "10000000-0000-4000-8000-000000000003",
  snapshot: "10000000-0000-4000-8000-000000000004",
};

const revision = {
  id: ids.revision,
  version: 1,
  world_model_id: ids.model,
  world_snapshot_id: ids.snapshot,
  snapshot_sha256: "a".repeat(64),
  scenario_id: null,
  scenario_sha256: null,
  cohort_id: null,
  cohort_sha256: null,
  semantic_experiment_id: null,
  experiment_sha256: null,
  created_at: "2026-08-12T12:00:00Z",
};

describe("decision-thread contracts", () => {
  it("accepts a strict snapshot-only thread history", () => {
    const detail = decisionThreadDetailSchema.parse({
      id: ids.thread,
      title: "Tourism decision",
      decision_question: "Which intervention should be evaluated?",
      created_at: "2026-08-12T12:00:00Z",
      latest_revision: revision,
      revisions: [revision],
    });

    expect(detail.latest_revision?.version).toBe(1);
  });

  it("accepts a question-first draft without a context revision", () => {
    expect(decisionThreadDraftCreateRequestSchema.parse({
      title: "Tourism decision",
      decision_question: "Which intervention should be evaluated?",
    })).toEqual({
      title: "Tourism decision",
      decision_question: "Which intervention should be evaluated?",
    });
    expect(decisionThreadDetailSchema.parse({
      id: ids.thread,
      title: "Tourism decision",
      decision_question: "Which intervention should be evaluated?",
      created_at: "2026-08-12T12:00:00Z",
      latest_revision: null,
      revisions: [],
    }).latest_revision).toBeNull();
  });

  it("rejects experiment context without both scenario and cohort", () => {
    expect(() => decisionThreadContextRequestSchema.parse({
      world_model_id: ids.model,
      world_snapshot_id: ids.snapshot,
      scenario_id: null,
      cohort_id: null,
      semantic_experiment_id: ids.thread,
    })).toThrow(/Experiment requires Scenario and Cohort/);
  });

  it("rejects non-contiguous revision history", () => {
    expect(() => decisionThreadDetailSchema.parse({
      id: ids.thread,
      title: "Tourism decision",
      decision_question: "Which intervention should be evaluated?",
      created_at: "2026-08-12T12:00:00Z",
      latest_revision: { ...revision, version: 2 },
      revisions: [{ ...revision, version: 2 }],
    })).toThrow(/Revision versions must be contiguous/);
  });
});
