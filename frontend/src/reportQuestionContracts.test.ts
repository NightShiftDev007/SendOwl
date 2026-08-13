import { describe, expect, it } from "vitest";

import { reportQuestionSchema } from "./reportQuestionContracts";

const base = {
  id: "18ac1504-3b0c-4516-a926-22333618786e",
  report_id: "c9fb3174-165c-40a4-bf22-1bcc1a7ed10f",
  report_sha256: "a".repeat(64),
  graph_id: "58a31b78-c805-4b18-90c3-b35920c612dd",
  graph_sha256: "b".repeat(64),
  question: "What does the evidence establish?",
  question_sha256: "c".repeat(64),
  model_name: "qwen3.7-plus",
  semantic_config_sha256: "d".repeat(64),
  prompt_schema_version: "report-evidence-qa/v1",
  created_at: "2026-08-13T10:00:00+08:00",
};

describe("reportQuestionSchema", () => {
  it("accepts a succeeded answer with exact citations", () => {
    const parsed = reportQuestionSchema.parse({
      ...base,
      status: "succeeded",
      started_at: "2026-08-13T10:00:01+08:00",
      completed_at: "2026-08-13T10:00:03+08:00",
      answer_markdown: "The evidence establishes a bounded observation.",
      citations: [{
        position: 0,
        article_id: "92db4070-ad03-46d6-a471-300080541591",
        quote: "Exact evidence",
        start_offset: 4,
        end_offset: 18,
      }],
      answer_sha256: "e".repeat(64),
      error_code: null,
      error_message: null,
    });

    expect(parsed.citations).toHaveLength(1);
  });

  it("rejects a success without citations", () => {
    expect(() => reportQuestionSchema.parse({
      ...base,
      status: "succeeded",
      started_at: "2026-08-13T10:00:01+08:00",
      completed_at: "2026-08-13T10:00:03+08:00",
      answer_markdown: "Uncited answer",
      citations: [],
      answer_sha256: "e".repeat(64),
      error_code: null,
      error_message: null,
    })).toThrow();
  });

  it("rejects extra response fields", () => {
    expect(() => reportQuestionSchema.parse({
      ...base,
      status: "queued",
      started_at: null,
      completed_at: null,
      answer_markdown: null,
      citations: [],
      answer_sha256: null,
      error_code: null,
      error_message: null,
      unsupported: true,
    })).toThrow();
  });
});
