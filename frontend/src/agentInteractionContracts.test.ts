import { describe, expect, it } from "vitest";

import { agentInteractionSchema } from "./agentInteractionContracts";

const id = "10000000-0000-4000-8000-000000000001";
const digest = "a".repeat(64);

describe("Agent Interaction contracts", () => {
  it("accepts a queued root bound to one ReportAgent draft", () => {
    const item = {
      id,
      research_project_id: "10000000-0000-4000-8000-000000000002",
      research_simulation_run_id: "10000000-0000-4000-8000-000000000003",
      report_agent_run_id: "10000000-0000-4000-8000-000000000004",
      report_agent_run_sha256: digest,
      report_agent_draft_id: "10000000-0000-4000-8000-000000000005",
      report_agent_draft_sha256: digest,
      source_sha256: digest,
      question: "这次模拟记录了什么？",
      interaction_sha256: digest,
      model_name: "qwen",
      semantic_config_sha256: digest,
      prompt_schema_version: "sandowl-agent-interaction/v1",
      parent_interaction_id: null,
      parent_interaction_sha256: null,
      parent_answer_sha256: null,
      conversation_depth: 0,
      status: "queued",
      created_at: "2026-08-16T09:00:00Z",
      started_at: null,
      completed_at: null,
      answer_markdown: null,
      citations: [],
      answer_sha256: null,
      error_code: null,
      error_message: null,
    };

    expect(agentInteractionSchema.parse(item).report_agent_draft_id).toBe(
      "10000000-0000-4000-8000-000000000005",
    );
  });

  it("rejects DecisionReport-style detached lineage", () => {
    const invalid = {
      id,
      research_project_id: "10000000-0000-4000-8000-000000000002",
      research_simulation_run_id: "10000000-0000-4000-8000-000000000003",
      report_agent_run_id: "10000000-0000-4000-8000-000000000004",
      report_agent_run_sha256: digest,
      report_agent_draft_id: "10000000-0000-4000-8000-000000000005",
      report_agent_draft_sha256: digest,
      source_sha256: digest,
      question: "继续追问",
      interaction_sha256: digest,
      model_name: "qwen",
      semantic_config_sha256: digest,
      prompt_schema_version: "sandowl-agent-interaction/v2",
      parent_interaction_id: null,
      parent_interaction_sha256: null,
      parent_answer_sha256: null,
      conversation_depth: 1,
      status: "queued",
      created_at: "2026-08-16T09:00:00Z",
      started_at: null,
      completed_at: null,
      answer_markdown: null,
      citations: [],
      answer_sha256: null,
      error_code: null,
      error_message: null,
    };

    expect(agentInteractionSchema.safeParse(invalid).success).toBe(false);
  });
});
