import { describe, expect, it } from "vitest";

import {
  researchPersonaInterviewSchema,
  researchPersonaInterviewsResponseSchema,
} from "./researchInterviewContracts";

const timestamp = "2026-08-18T08:00:00+00:00";

function queuedInterview() {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    research_project_id: "00000000-0000-4000-8000-000000000002",
    research_simulation_run_id: "00000000-0000-4000-8000-000000000003",
    run_spec_sha256: "a".repeat(64),
    graph_memory_sha256: "b".repeat(64),
    cohort_id: "00000000-0000-4000-8000-000000000004",
    cohort_sha256: "c".repeat(64),
    persona: {
      id: "00000000-0000-4000-8000-000000000005",
      position: 0,
      persona_id: "persona-1",
      display_name: "合成人物一",
      profile_sha256: "d".repeat(64),
    },
    question: "你为什么评论？",
    source_sha256: "e".repeat(64),
    interview_sha256: "f".repeat(64),
    model_name: "qwen",
    semantic_config_sha256: "0".repeat(64),
    prompt_schema_version: "sandowl-run-persona-interview/v1" as const,
    status: "queued" as const,
    created_at: timestamp,
    started_at: null,
    completed_at: null,
    answer_markdown: null,
    citations: [],
    answer_sha256: null,
    error_code: null,
    error_message: null,
  };
}

describe("research interview contracts", () => {
  it("accepts a queued interview bound to graph memory", () => {
    expect(researchPersonaInterviewSchema.parse(queuedInterview()).status).toBe("queued");
  });

  it("requires response total to equal its items", () => {
    expect(() => researchPersonaInterviewsResponseSchema.parse({
      items: [queuedInterview()],
      total: 0,
    })).toThrow(/total/i);
  });
});
