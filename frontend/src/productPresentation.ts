import type { ResearchRunReport } from "./researchProjectContracts";

export function formatProductResourceTitle(value: string): string {
  return value.replaceAll("SendOwl", "SandOwl");
}

const runActionLabels = {
  create_post: "发布帖子",
  create_comment: "发表评论",
  like_post: "点赞帖子",
  dislike_post: "点踩帖子",
  do_nothing: "未采取动作",
} as const;

export function formatRunActionType(value: keyof typeof runActionLabels): string {
  return runActionLabels[value];
}

const runLimitationTranslations: Readonly<Record<string, string>> = {
  "OpenAI-compatible provider behavior is nondeterministic; the recorded seed does not guarantee provider-level reproducibility.": "兼容 OpenAI 接口的模型服务存在非确定性；记录的随机种子不能保证模型服务层完全复现。",
  "This social simulation is limited to at most eight personas and three rounds on Reddit.": "这条封存记录保留旧版“三轮上限”说明；当前产品最多支持六轮，本次实际轮数以运行配置为准。",
  "This social simulation is limited to at most eight personas and six rounds on Reddit.": "本次社交模拟仅支持 Reddit 环境，最多八名合成人物、六轮运行。",
  "The trial has no real social network; agents only observe OASIS recommendations.": "本次运行不包含真实社交关系网络；合成人物只观察模拟平台推荐内容。",
  "Persona prompts use a deterministic bounded projection of at most forty informative profile attributes and do not contain hidden analysis instructions.": "人物提示词只使用最多四十个信息属性的确定性有界投影，不包含隐藏分析指令。",
  "Events are observed actions only; no stance, reach, prediction, or decision verdict is inferred.": "事件只记录观察到的动作；系统不推断立场、触达范围、现实预测或决策结论。",
};

export function formatRunLimitation(value: string): string {
  return runLimitationTranslations[value] ?? value;
}

export interface ResearchReportReaderSummary {
  readonly headline: string;
  readonly detail: string;
  readonly canSay: readonly string[];
  readonly cannotSay: readonly string[];
}

function joinObservationParts(parts: readonly string[]): string {
  if (parts.length === 0) return "没有记录到合成人物的可见动作";
  if (parts.length === 1) return `记录到${parts[0]}`;
  return `记录到${parts.slice(0, -1).join("、")}和${parts.at(-1) ?? ""}`;
}

export function buildResearchReportReaderSummary(
  report: ResearchRunReport,
): ResearchReportReaderSummary {
  const result = report.run.result;
  if (result === null) {
    return {
      headline: "这次模拟尚未形成可读的观测结果。",
      detail: "研究上下文与运行配置已经封存，但当前报告没有可汇总的事件计数。",
      canSay: ["本次运行使用了指定的冻结证据、合成人群与起始内容。"],
      cannotSay: ["不能据此描述合成人物的行为，也不能推断现实效果。"],
    };
  }

  const actionParts = [
    result.generated_post_count > 0 ? `${result.generated_post_count} 条人物新增帖子` : null,
    result.comment_count > 0 ? `${result.comment_count} 条评论` : null,
    result.reaction_count > 0 ? `${result.reaction_count} 次反应` : null,
    result.do_nothing_count > 0 ? `${result.do_nothing_count} 次未采取动作` : null,
  ].filter((value): value is string => value !== null);
  const noGeneratedPost = result.generated_post_count === 0
    ? "没有合成人物另行发布新帖。"
    : "";
  const presetLabel = result.initial_post_count === 1
    ? "1 条预置说明"
    : `${result.initial_post_count} 条预置内容`;

  return {
    headline: `在 ${presetLabel}之后，${joinObservationParts(actionParts)}。`,
    detail: `${noGeneratedPost}预置说明用于启动模拟，不属于合成人物生成的内容。`.trim(),
    canSay: [
      `在 Seed ${report.run.seed}、${report.run.rounds ?? "—"} 轮、${report.run.cohort.persona_count} 名合成人物的设定下，系统记录了上述动作。`,
      "每条计数都可以回到本次冻结运行的事件记录。",
    ],
    cannotSay: [
      "不说明现实用户会作出相同行为，也不衡量这则说明的实际传播或经营效果。",
      "不构成方案比较、现实预测、法律意见或行动建议。",
    ],
  };
}

export function formatReportBodyForReader(value: string): string {
  return value
    .replace(/\[\d+:\d+\]/gu, "")
    .replace(/[ \t]+([，。；：！？])/gu, "$1")
    .replace(/[ \t]{2,}/gu, " ")
    .trim();
}
