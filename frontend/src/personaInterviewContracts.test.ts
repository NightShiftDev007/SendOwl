import { describe, expect, it } from "vitest";

import { personaInterviewSchema, personaInterviewSessionSchema } from "./personaInterviewContracts";

const uuid = "10000000-0000-4000-8000-000000000001";

function succeededInterview(): Record<string, unknown> {
  return {
    id: uuid,
    report_id: "10000000-0000-4000-8000-000000000002",
    report_sha256: "a".repeat(64),
    cohort_id: "10000000-0000-4000-8000-000000000003",
    cohort_sha256: "b".repeat(64),
    persona: {
      id: "10000000-0000-4000-8000-000000000004",
      position: 0,
      persona_id: "persona-1",
      display_name: "Persona One",
      profile_sha256: "c".repeat(64),
    },
    question: "What matters to you?",
    interview_sha256: "d".repeat(64),
    model_name: "qwen",
    semantic_config_sha256: "e".repeat(64),
    prompt_schema_version: "persona-report-interview/v1",
    status: "succeeded",
    created_at: "2026-08-13T10:00:00+08:00",
    started_at: "2026-08-13T10:00:01+08:00",
    completed_at: "2026-08-13T10:00:02+08:00",
    answer_markdown: "Synthetic perspective.",
    cited_section_positions: [0, 2],
    answer_sha256: "f".repeat(64),
    error_code: null,
    error_message: null,
  };
}

describe("personaInterviewSchema", () => {
  it("accepts a content-addressed synthetic Persona answer", () => {
    expect(personaInterviewSchema.parse(succeededInterview()).cited_section_positions).toEqual([0, 2]);
  });

  it("rejects duplicate or unsorted section citations", () => {
    expect(() => personaInterviewSchema.parse({
      ...succeededInterview(),
      cited_section_positions: [2, 0],
    })).toThrow();
  });

  it("rejects succeeded answers without report section citations", () => {
    expect(() => personaInterviewSchema.parse({
      ...succeededInterview(),
      cited_section_positions: [],
    })).toThrow();
  });
});

describe("personaInterviewSessionSchema", () => {
  it("accepts an atomic ordered multi-Persona session", () => {
    const first = succeededInterview();
    const second = {
      ...succeededInterview(),
      id: "10000000-0000-4000-8000-000000000005",
      persona: {
        ...(succeededInterview().persona as Record<string, unknown>),
        id: "10000000-0000-4000-8000-000000000006",
        position: 1,
        persona_id: "persona-2",
        display_name: "Persona Two",
      },
    };
    const session = personaInterviewSessionSchema.parse({
      id: "10000000-0000-4000-8000-000000000007",
      report_id: first.report_id,
      report_sha256: first.report_sha256,
      cohort_id: first.cohort_id,
      cohort_sha256: first.cohort_sha256,
      question: first.question,
      persona_count: 2,
      session_sha256: "1".repeat(64),
      model_name: first.model_name,
      semantic_config_sha256: first.semantic_config_sha256,
      prompt_schema_version: "persona-report-interview-session/v1",
      status: "succeeded",
      created_at: first.created_at,
      interviews: [first, second],
    });

    expect(session.interviews).toHaveLength(2);
  });

  it("rejects a lifecycle status not derived from child interviews", () => {
    const base = succeededInterview();
    const first = { ...base, status: "queued", started_at: null, completed_at: null, answer_markdown: null, cited_section_positions: [], answer_sha256: null };
    const second = { ...first, id: "10000000-0000-4000-8000-000000000005", persona: { ...(base.persona as Record<string, unknown>), id: "10000000-0000-4000-8000-000000000006", position: 1, persona_id: "persona-2" } };
    expect(() => personaInterviewSessionSchema.parse({
      id: "10000000-0000-4000-8000-000000000007", report_id: base.report_id,
      report_sha256: base.report_sha256, cohort_id: base.cohort_id,
      cohort_sha256: base.cohort_sha256, question: base.question, persona_count: 2,
      session_sha256: "1".repeat(64), model_name: base.model_name,
      semantic_config_sha256: base.semantic_config_sha256,
      prompt_schema_version: "persona-report-interview-session/v1", status: "succeeded",
      created_at: base.created_at, interviews: [first, second],
    })).toThrow();
  });
});
