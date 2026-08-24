import { describe, expect, it } from "vitest";

import {
  buildResearchReportReaderSummary,
  formatReportBodyForReader,
  formatProductResourceTitle,
  formatRunActionType,
  formatRunLimitation,
} from "./productPresentation";
import { researchRunReportSchema } from "./researchProjectContracts";

const reportFixture = researchRunReportSchema.parse({
  id: "fd81c881-345d-4bab-9ca2-97b82affd1a2",
  research_project: {
    id: "748de69e-3192-496d-9b2c-6ca72ac85575",
    title: "原生中文案例",
    research_question: "观察到了什么？",
    snapshot: {
      world_model_id: "3d493c23-3603-4ec9-8096-d8af17d98b21",
      world_snapshot_id: "b1353579-a59a-46c7-84cf-9b5dcc6986ee",
      snapshot_sha256: "a".repeat(64),
    },
    graph: null,
    schema_version: "sandowl-research-project/v2",
    legacy_design: null,
    project_sha256: "b".repeat(64),
    created_at: "2026-08-17T00:00:00Z",
  },
  run: {
    id: "32f4e1ed-985e-4786-b965-4e37436bda9f",
    research_project_id: "748de69e-3192-496d-9b2c-6ca72ac85575",
    project_sha256: "b".repeat(64),
    schema_version: "sandowl-research-simulation-run/v2",
    cohort: {
      cohort_id: "415caf8a-1ce0-4d75-a699-7d5a402fcb79",
      cohort_sha256: "c".repeat(64),
      persona_count: 5,
    },
    simulation_requirement: "观察合成人物动作。",
    seed: 20260817,
    rounds: 1,
    minutes_per_round: 60,
    initial_post: "虚构平台发布说明。",
    engine: "camel-oasis",
    engine_version: "0.2.5",
    model_name: "model",
    semantic_config_sha256: "d".repeat(64),
    prompt_schema_version: "matraix-semantic-profile/v1",
    simulation_context: null,
    simulation_context_sha256: null,
    simulation_plan: null,
    simulation_plan_sha256: null,
    status: "succeeded",
    run_spec_sha256: "e".repeat(64),
    created_at: "2026-08-17T00:00:00Z",
    started_at: "2026-08-17T00:00:01Z",
    completed_at: "2026-08-17T00:01:00Z",
    result: {
      artifact_sha256: "f".repeat(64),
      artifact_size_bytes: 100,
      user_count: 5,
      initial_post_count: 1,
      generated_post_count: 0,
      comment_count: 1,
      reaction_count: 3,
      do_nothing_count: 1,
      observed_action_count: 6,
      rounds_completed: 1,
      limitations: [],
    },
    error: null,
  },
  events: [],
  graph_memory: [],
  report_sha256: "0".repeat(64),
  created_at: "2026-08-17T00:02:00Z",
});

describe("product resource title presentation", () => {
  it("normalizes the retired product name without mutating unrelated text", () => {
    expect(formatProductResourceTitle("SendOwl E2E Demo")).toBe("SandOwl E2E Demo");
    expect(formatProductResourceTitle("Northstar response cohort")).toBe(
      "Northstar response cohort",
    );
  });

  it("localizes fixed run enums and limitations without inventing unknown text", () => {
    expect(formatRunActionType("create_comment")).toBe("发表评论");
    expect(formatRunLimitation(
      "Events are observed actions only; no stance, reach, prediction, or decision verdict is inferred.",
    )).toBe("事件只记录观察到的动作；系统不推断立场、触达范围、现实预测或决策结论。");
    expect(formatRunLimitation(
      "This social simulation is limited to at most eight personas and three rounds on Reddit.",
    )).toBe("这条封存记录保留旧版“三轮上限”说明；当前产品最多支持六轮，本次实际轮数以运行配置为准。");
    expect(formatRunLimitation("Provider-specific limitation.")).toBe(
      "Provider-specific limitation.",
    );
  });

  it("builds a reader summary that separates the preset post from persona activity", () => {
    expect(buildResearchReportReaderSummary(reportFixture)).toEqual({
      headline: "在 1 条预置说明之后，记录到1 条评论、3 次反应和1 次未采取动作。",
      detail: "没有合成人物另行发布新帖。预置说明用于启动模拟，不属于合成人物生成的内容。",
      canSay: [
        "在 Seed 20260817、1 轮、5 名合成人物的设定下，系统记录了上述动作。",
        "每条计数都可以回到本次冻结运行的事件记录。",
      ],
      cannotSay: [
        "不说明现实用户会作出相同行为，也不衡量这则说明的实际传播或经营效果。",
        "不构成方案比较、现实预测、法律意见或行动建议。",
      ],
    });
  });

  it("counts every scheduled preset item in the reader headline", () => {
    const scheduledReport = {
      ...reportFixture,
      run: {
        ...reportFixture.run,
        result: {
          ...reportFixture.run.result!,
          initial_post_count: 2,
        },
      },
    };

    expect(buildResearchReportReaderSummary(scheduledReport).headline).toBe(
      "在 2 条预置内容之后，记录到1 条评论、3 次反应和1 次未采取动作。",
    );
  });

  it("removes technical citation markers from reader copy", () => {
    expect(formatReportBodyForReader("单 seed 不能保证复现 [0:12]。  仅描述动作[0:13]。"))
      .toBe("单 seed 不能保证复现。 仅描述动作。");
  });
});
