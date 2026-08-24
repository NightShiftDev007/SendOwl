import { describe, expect, it } from "vitest";

import { decisionReportV2Schema } from "./decisionReportV2Contracts";

const uuid = (value: number): string => `20000000-0000-4000-8000-${value.toString().padStart(12, "0")}`;
const digest = (value: string): string => value.repeat(64 / value.length);

function variantPayload(position: number, role: "baseline" | "alternative"): Record<string, unknown> {
  return {
    id: uuid(position + 10),
    position,
    role,
    name: role === "baseline" ? "基线" : `备选 ${position}`,
    hypothesis: "只用于受限实验观察。",
    interventions: role === "baseline" ? [] : [{
      id: uuid(position + 20),
      kind: "initial_post",
      actor: "scenario_actor",
      channel: "reddit",
      content: "synthetic demo data",
      offset_minutes: 0,
      provenance: "scenario_assumption",
      synthetic_label: "synthetic demo data",
    }],
  };
}

function reportPayload(): Record<string, unknown> {
  const variants = [variantPayload(0, "baseline"), variantPayload(1, "alternative")];
  const trial = (id: number, variantId: string): Record<string, unknown> => ({
    id: uuid(id),
    variant_id: variantId,
    role: variantId === uuid(10) ? "baseline" : "alternative",
    seed: 20260816,
    trial_sha256: digest("a"),
    status: "succeeded",
    created_at: "2026-08-16T10:00:00Z",
    started_at: "2026-08-16T10:00:01Z",
    completed_at: "2026-08-16T10:01:00Z",
    artifact_sha256: digest("b"),
    rounds_completed: 1,
    failure: null,
  });
  const observation = {
    trial_id: uuid(30),
    variant_id: uuid(10),
    seed: 20260816,
    status: "succeeded",
    event_count: 1,
    events_sha256: digest("c"),
    event_endpoint: "/api/v2/semantic-trials/20000000-0000-4000-8000-000000000030/events",
    normalized_counts: {
      scenario_initial_posts: 0,
      generated_posts: 1,
      comments: 0,
      reactions: 0,
      do_nothing: 0,
      observed_actions: 1,
      authored_content: 1,
    },
    event_clock_boundary: {
      observed_at_raw_semantics: "simulation clock",
      recorded_at_semantics: "persistence clock",
    },
  };
  return {
    id: uuid(1),
    experiment_id: uuid(2),
    experiment_sha256: digest("d"),
    scenario_id: uuid(3),
    scenario_sha256: digest("e"),
    cohort_id: uuid(4),
    cohort_sha256: digest("f"),
    world_snapshot_id: uuid(5),
    world_snapshot_sha256: digest("a"),
    title: "决策报告 V2：测试",
    report_sha256: digest("b"),
    generator_version: "decision-report/v2",
    created_at: "2026-08-16T10:04:00Z",
    sections: [
      {
        position: 0,
        kind: "evidence",
        title: "Evidence",
        body_markdown: "冻结证据。",
        data: {
          payload_kind: "evidence",
          world_snapshot: {
            world_model_id: uuid(6),
            world_snapshot_id: uuid(5),
            version: 1,
            snapshot_sha256: digest("a"),
            created_at: "2026-08-16T09:00:00Z",
            sealed_at: "2026-08-16T09:00:00Z",
            verification: "human_confirmed",
          },
          sources: [{
            evidence_kind: "media_article",
            source_id: uuid(7),
            source_name: "AgendaScope",
            original_url: "https://example.com/article",
            title: "Frozen source",
            published_at: "2026-08-15T10:00:00Z",
            publication_date: null,
            captured_at: "2026-08-16T09:00:00Z",
            content_sha256: digest("b"),
            identity_sha256: digest("b"),
            excerpt: "Frozen excerpt",
          }],
          evidence_boundary: {
            status: "frozen_source_copy_not_independent_fact_check",
            statements: ["Source copy is frozen."],
          },
        },
      },
      {
        position: 1,
        kind: "assumptions",
        title: "Assumptions",
        body_markdown: "Scenario assumptions。",
        data: {
          payload_kind: "assumptions",
          scenario: {
            id: uuid(3),
            scenario_sha256: digest("e"),
            title: "Scenario",
            decision_question: "观察什么？",
            world_snapshot_id: uuid(5),
            snapshot_sha256: digest("a"),
            variants,
          },
          assumption_boundary: ["Not evidence."],
        },
      },
      {
        position: 2,
        kind: "experiment",
        title: "Experiment",
        body_markdown: "Experiment config。",
        data: {
          payload_kind: "experiment",
          experiment: {
            id: uuid(2),
            experiment_sha256: digest("d"),
            status: "succeeded",
            scenario_id: uuid(3),
            scenario_sha256: digest("e"),
            cohort_id: uuid(4),
            cohort_sha256: digest("f"),
            dataset_sha256: digest("c"),
            persona_count: 1,
            variants,
            seeds: [20260816],
            rounds: 1,
            minutes_per_round: 60,
            model_name: "qwen3.7-plus",
            semantic_config_sha256: digest("d"),
            prompt_schema_version: "matraix-semantic-profile/v1",
            engine_version: "0.2.5",
            camel_version: "0.2.78",
          },
          trials: [trial(30, uuid(10)), trial(31, uuid(11))],
        },
      },
      {
        position: 3,
        kind: "observation",
        title: "Observation",
        body_markdown: "Observed events。",
        data: { payload_kind: "observation", trials: [observation, { ...observation, trial_id: uuid(31), variant_id: uuid(11) }], behavior_changes: [{ statement: "One event persisted.", basis: ["observation:trial"] }] },
      },
      {
        position: 4,
        kind: "comparison",
        title: "Comparison",
        body_markdown: "Comparison。",
        data: {
          payload_kind: "comparison",
          metrics: [{
            metric: "observed_action_count",
            variants: [
              { variant_id: uuid(10), name: "基线", role: "baseline", mean: 1, stddev: 0, n: 1 },
              { variant_id: uuid(11), name: "备选 1", role: "alternative", mean: 2, stddev: 0, n: 1 },
            ],
            alternatives: [{
              variant_id: uuid(11), name: "备选 1", mean: 2, stddev: 0, n: 1,
              mean_delta: 1, stddev_delta: 0, paired_seeds: [20260816], paired_seed_count: 1,
            }],
          }],
          comparison_state: "complete",
          pairing_rule: "same seed",
          comparison_boundary: ["Descriptive only."],
        },
      },
      {
        position: 5,
        kind: "analysis",
        title: "Analysis",
        body_markdown: "Explanation only。",
        data: {
          payload_kind: "analysis",
          statements: [{ statement_id: "scope", text: "This is bounded.", basis: ["comparison"], allowed_type: "scope_explanation" }],
          prohibited_claims: ["future prediction", "best option"],
        },
      },
      {
        position: 6,
        kind: "limitations",
        title: "Limitations",
        body_markdown: "Limitations。",
        data: {
          payload_kind: "limitations",
          items: [{ code: "sample_size", text: "Small cohort.", severity: "material" }],
        },
      },
    ],
  };
}

describe("decision report V2 contracts", () => {
  it("accepts the typed seven-section outline", () => {
    const report = decisionReportV2Schema.parse(reportPayload());
    expect(report.sections).toHaveLength(7);
    expect(report.sections[0]?.data.payload_kind).toBe("evidence");
  });

  it("rejects a section whose kind and payload discriminator disagree", () => {
    const payload = reportPayload();
    const first = (payload.sections as Array<Record<string, unknown>>)[0];
    if (first === undefined) {
      throw new Error("fixture must contain seven sections");
    }
    first.kind = "analysis";
    expect(() => decisionReportV2Schema.parse(payload)).toThrow(/kind does not match/);
  });

  it("rejects unrelated top-level fields", () => {
    expect(() => decisionReportV2Schema.parse({ ...reportPayload(), verdict: "best" })).toThrow();
  });
});
