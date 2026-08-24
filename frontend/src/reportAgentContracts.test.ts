import { describe, expect, it } from "vitest";

import {
  reportAgentCitedDraftSchema,
  reportAgentRunRequestSchema,
  reportAgentRunSchema,
} from "./reportAgentContracts";

const runId = "0a1db401-8315-40b5-b4d1-36fc5e666766";
const modelId = "818ff23d-1a31-4d47-861c-913e64fa8398";
const snapshotId = "7a92810f-43ea-405c-ab81-4e52f28293cd";
const digest = "a".repeat(64);

const request = {
  world_model_id: modelId,
  world_snapshot_id: snapshotId,
  snapshot_sha256: digest,
  objective: "整理当前快照能够支持的观察与限制。",
  outline: [
    { position: 0, title: "证据观察", focus: "读取媒体和政策证据。" },
    { position: 1, title: "限制", focus: "说明证据尚不能证明的事项。" },
  ],
  max_tool_calls: 6,
};

describe("bounded ReportAgent contracts", () => {
  it("accepts a contiguous bounded plan", () => {
    expect(reportAgentRunRequestSchema.parse(request).outline).toHaveLength(2);
  });

  it("rejects a detached outline position", () => {
    const invalid = {
      ...request,
      outline: [request.outline[0], { ...request.outline[1], position: 2 }],
    };
    expect(reportAgentRunRequestSchema.safeParse(invalid).success).toBe(false);
  });

  it("rejects an inconsistent audit budget", () => {
    const invalid = {
      id: runId,
      ...request,
      schema_version: "bounded-report-agent-evidence/v1",
      research_simulation_run_id: null,
      research_run_report_sha256: null,
      run_sha256: digest,
      created_at: "2026-08-16T09:00:00Z",
      tool_calls: [],
      tool_call_count: 0,
      remaining_tool_calls: 5,
    };
    expect(reportAgentRunSchema.safeParse(invalid).success).toBe(false);
  });

  it("accepts a succeeded draft with exact citation offsets", () => {
    const draft = {
      id: "f49749b3-11be-4102-bf28-896cc58cdf06",
      run_id: runId,
      run_sha256: digest,
      evidence_call_count: 1,
      evidence_calls_sha256: digest,
      input_sha256: digest,
      retry_of_draft_id: null,
      retry_of_input_sha256: null,
      attempt_number: 1,
      model_name: "qwen",
      semantic_config_sha256: digest,
      prompt_schema_version: "bounded-report-agent-cited-draft/v1",
      status: "succeeded",
      created_at: "2026-08-16T09:00:00Z",
      started_at: "2026-08-16T09:00:01Z",
      completed_at: "2026-08-16T09:00:02Z",
      title: "受控草稿",
      sections: request.outline.map((section) => ({
        position: section.position,
        title: section.title,
        body_markdown: "仅陈述冻结证据。",
        citations: [{
          position: 0,
          evidence_kind: "media_article",
          target_id: "b84779f0-04c5-43a7-a62d-fdb2a217f56a",
          tool_call_position: 0,
          source_label: "来源",
          quote: "冻结证据",
          start_offset: 2,
          end_offset: 6,
        }],
      })),
      draft_sha256: digest,
      error_code: null,
      error_message: null,
    };

    expect(reportAgentCitedDraftSchema.parse(draft).sections).toHaveLength(2);
  });

  it("accepts an immutable retry that preserves the input digest", () => {
    const failedRetry = {
      id: "54c89aec-43e6-4f35-ac60-d04a0282e122",
      run_id: runId,
      run_sha256: digest,
      evidence_call_count: 1,
      evidence_calls_sha256: digest,
      input_sha256: digest,
      retry_of_draft_id: "f49749b3-11be-4102-bf28-896cc58cdf06",
      retry_of_input_sha256: digest,
      attempt_number: 2,
      model_name: "qwen",
      semantic_config_sha256: digest,
      prompt_schema_version: "bounded-report-agent-cited-draft/v1",
      status: "failed",
      created_at: "2026-08-16T09:00:03Z",
      started_at: "2026-08-16T09:00:04Z",
      completed_at: "2026-08-16T09:00:05Z",
      title: null,
      sections: [],
      draft_sha256: null,
      error_code: "semantic_execution",
      error_message: "Strict output validation failed.",
    };

    expect(reportAgentCitedDraftSchema.parse(failedRetry).attempt_number).toBe(2);
  });

  it("accepts a ReportAgent scope bound to one simulation run", () => {
    const researchRunId = "c1541bc3-e478-4c03-8b5c-7d09bd9ed109";
    const run = {
      id: runId,
      ...request,
      schema_version: "sandowl-research-run-report-agent/v1",
      research_simulation_run_id: researchRunId,
      research_run_report_sha256: digest,
      max_tool_calls: 1,
      run_sha256: digest,
      created_at: "2026-08-16T09:00:00Z",
      tool_calls: [{
        id: "ac5267f0-a77f-4baa-a484-a96677822b67",
        run_id: runId,
        position: 0,
        tool_name: "read_simulation_run",
        target_id: researchRunId,
        input_sha256: digest,
        result_sha256: digest,
        call_sha256: digest,
        created_at: "2026-08-16T09:00:00Z",
      }],
      tool_call_count: 1,
      remaining_tool_calls: 0,
    };

    expect(reportAgentRunSchema.parse(run).research_simulation_run_id).toBe(researchRunId);
  });

  it("accepts a v2 multi-source research report scope", () => {
    const researchRunId = "c1541bc3-e478-4c03-8b5c-7d09bd9ed109";
    const run = {
      id: runId,
      ...request,
      schema_version: "sandowl-research-run-report-agent/v2",
      research_simulation_run_id: researchRunId,
      research_run_report_sha256: digest,
      max_tool_calls: 2,
      run_sha256: digest,
      created_at: "2026-08-16T09:00:00Z",
      tool_calls: ["read_world_snapshot", "read_simulation_run"].map((toolName, position) => ({
        id: position === 0
          ? "ac5267f0-a77f-4baa-a484-a96677822b67"
          : "6543a312-c084-41ec-ae18-24763569412e",
        run_id: runId,
        position,
        tool_name: toolName,
        target_id: position === 0 ? snapshotId : researchRunId,
        input_sha256: digest,
        result_sha256: digest,
        call_sha256: digest,
        created_at: "2026-08-16T09:00:00Z",
      })),
      tool_call_count: 2,
      remaining_tool_calls: 0,
    };

    expect(reportAgentRunSchema.parse(run).tool_calls).toHaveLength(2);
  });
});
