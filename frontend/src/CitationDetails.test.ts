import { describe, expect, it } from "vitest";

import {
  explainCitationForReader,
  formatCitationSourceLabel,
} from "./CitationDetails";

describe("citation presentation", () => {
  it("localizes the native frozen-run source without changing unknown labels", () => {
    expect(formatCitationSourceLabel("SandOwl: sealed single-run simulation record")).toBe(
      "SandOwl：冻结的单次合成模拟记录",
    );
    expect(formatCitationSourceLabel("外部来源")).toBe("外部来源");
  });

  it("turns frozen simulation fragments into a reader-facing relationship", () => {
    expect(explainCitationForReader({
      evidence_kind: "simulation_run",
      quote: "Events are observed actions only; no decision verdict is inferred.",
    })).toEqual({
      title: "支持“只记录动作，不推断现实结论”",
      body: "冻结记录只保存观察到的模拟动作，不据此推断立场、触达范围、现实预测或决策结论。",
    });
  });

  it("keeps real media evidence distinct from synthetic run evidence", () => {
    expect(explainCitationForReader({
      evidence_kind: "media_article",
      quote: "Frozen article excerpt.",
    }).title).toBe("现实媒体来源");
  });

  it("distinguishes legacy three-round evidence from the current six-round limit", () => {
    expect(explainCitationForReader({
      evidence_kind: "simulation_run",
      quote: "This social simulation is limited to at most eight personas and three rounds on Reddit.",
    }).body).toBe(
      "这段历史冻结原文保留旧版三轮上限；当前产品最多支持六轮，本次实际轮数仍以对应运行配置为准。",
    );
    expect(explainCitationForReader({
      evidence_kind: "simulation_run",
      quote: "This social simulation is limited to at most eight personas and six rounds on Reddit.",
    }).body).toBe("冻结记录写明当前社交模拟最多使用八名合成人物和六轮运行。");
  });
});
