import { describe, expect, it } from "vitest";

import { decisionReportSchema } from "./decisionReportContracts";

function reportPayload(): Record<string, unknown> {
  return {
    id: "10000000-0000-4000-8000-000000000001",
    experiment_id: "10000000-0000-4000-8000-000000000002",
    experiment_sha256: "a".repeat(64),
    scenario_id: "10000000-0000-4000-8000-000000000003",
    scenario_sha256: "b".repeat(64),
    cohort_id: "10000000-0000-4000-8000-000000000004",
    cohort_sha256: "c".repeat(64),
    title: "决策发现：测试实验",
    report_sha256: "d".repeat(64),
    generator_version: "deterministic-findings/v1",
    created_at: "2026-08-12T12:00:00Z",
    sections: [
      { position: 0, kind: "scope", title: "范围与问题", body_markdown: "范围", metrics: [] },
      {
        position: 1,
        kind: "comparison",
        title: "配对观测差异",
        body_markdown: "比较",
        metrics: [{
          metric: "observed_action_count",
          alternative_id: "10000000-0000-4000-8000-000000000005",
          alternative_name: "透明说明",
          baseline_mean: 2,
          alternative_mean: 3,
          mean_delta: 1,
          stddev_delta: 0,
          paired_seed_count: 1,
        }],
      },
      { position: 2, kind: "limitations", title: "解释限制", body_markdown: "限制", metrics: [] },
      { position: 3, kind: "provenance", title: "来源与完整性", body_markdown: "来源", metrics: [] },
    ],
  };
}

describe("decision report contracts", () => {
  it("accepts the fixed persisted findings outline", () => {
    expect(decisionReportSchema.parse(reportPayload()).sections).toHaveLength(4);
  });

  it("rejects reordered report chapters", () => {
    const payload = reportPayload();
    payload.sections = [...(payload.sections as object[])].reverse();
    expect(() => decisionReportSchema.parse(payload)).toThrow(/Report sections must be contiguous/);
  });

  it("rejects unrelated response fields", () => {
    expect(() => decisionReportSchema.parse({ ...reportPayload(), verdict: "best" })).toThrow();
  });
});
