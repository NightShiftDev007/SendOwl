import { describe, expect, it } from "vitest";

import { parentProgressSchema } from "./parentProgress";

const progress = {
  id: "24000000-0000-4000-8000-000000000001",
  status: "running",
  observed_at: "2026-08-16T12:00:00Z",
  attempt_number: 2,
  trial_count: 2,
  queued_trial_count: 0,
  running_trial_count: 1,
  succeeded_trial_count: 1,
  failed_trial_count: 0,
  event_count: 7,
  progress_sha256: "a".repeat(64),
} as const;

describe("parentProgressSchema", () => {
  it("accepts a consistent lightweight projection", () => {
    expect(parentProgressSchema.parse(progress).event_count).toBe(7);
  });

  it("rejects status or count drift", () => {
    expect(() => parentProgressSchema.parse({ ...progress, status: "succeeded" })).toThrow();
    expect(() => parentProgressSchema.parse({ ...progress, trial_count: 3 })).toThrow();
  });
});
