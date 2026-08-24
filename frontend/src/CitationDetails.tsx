import "./citationDetails.css";

type CitationEvidenceKind =
  | "media_article"
  | "policy_document"
  | "world_snapshot"
  | "world_graph"
  | "simulation_run"
  | "persona_interviews"
  | "research_run";

type CitationKindView =
  | { readonly evidence_kind: CitationEvidenceKind; readonly source_kind?: never }
  | { readonly source_kind: CitationEvidenceKind; readonly evidence_kind?: never };

type CitationView = CitationKindView & {
  readonly position: number;
  readonly quote: string;
  readonly source_label: string;
  readonly start_offset: number;
  readonly end_offset: number;
};

export interface CitationReaderExplanation {
  readonly title: string;
  readonly body: string;
}

export function formatCitationSourceLabel(sourceLabel: string): string {
  return sourceLabel === "SandOwl: sealed single-run simulation record"
    ? "SandOwl：冻结的单次合成模拟记录"
    : sourceLabel;
}

export function explainCitationForReader(
  citation: CitationKindView & Pick<CitationView, "quote">,
): CitationReaderExplanation {
  const evidenceKind = citation.evidence_kind ?? citation.source_kind;
  if (evidenceKind === undefined) {
    throw new Error("Citation must identify its evidence kind.");
  }
  const quote = citation.quote.toLowerCase();
  if (evidenceKind === "media_article") {
    return {
      title: "现实媒体来源",
      body: "这段冻结原文用于说明研究所依据的现实背景；它不验证后续合成模拟一定会在现实中发生。",
    };
  }
  if (evidenceKind === "policy_document") {
    return {
      title: "现实政策来源",
      body: "这段冻结原文用于限定研究所依据的政策背景；报告中的模拟观察仍属于合成结果。",
    };
  }
  if (evidenceKind === "world_snapshot") {
    return {
      title: "支持现实背景的冻结证据",
      body: "这段内容来自研究者明确选择并冻结的媒体或政策目录，只用于限定现实背景，不等同于后续合成情境。",
    };
  }
  if (evidenceKind === "world_graph") {
    return {
      title: "支持证据中的实体与关系",
      body: "这段内容来自冻结证据的语义图整理结果；它只表达有原文依据的实体或关系，不推断现实社会网络。",
    };
  }
  if (evidenceKind === "persona_interviews") {
    return {
      title: "支持运行后的 Persona 视角",
      body: "这段内容来自用户明确发起的运行后合成追问，不是真人访谈，也不是与仍在运行的代理实时通信。",
    };
  }
  if (evidenceKind === "research_run") {
    return {
      title: "支持这次 Persona 的合成回答",
      body: "这段文字直接来自已冻结的运行输入、事件或逐轮图记忆；它只支撑这次追加合成访谈，不代表现实人物观点。",
    };
  }
  if (quote.includes("nondeterministic") || quote.includes("does not guarantee provider-level reproducibility")) {
    return {
      title: "支持“单次运行不能保证完全复现”",
      body: "冻结记录明确说明模型服务存在非确定性；保存 Seed 可以复核输入，但不能保证再次得到完全相同的模型输出。",
    };
  }
  if (quote.includes("three rounds")) {
    return {
      title: "支持“模拟规模受到限制”",
      body: "这段历史冻结原文保留旧版三轮上限；当前产品最多支持六轮，本次实际轮数仍以对应运行配置为准。",
    };
  }
  if (quote.includes("at most eight personas") || quote.includes("six rounds")) {
    return {
      title: "支持“模拟规模受到限制”",
      body: "冻结记录写明当前社交模拟最多使用八名合成人物和六轮运行。",
    };
  }
  if (quote.includes("no real social network")) {
    return {
      title: "支持“没有真实社交关系网络”",
      body: "冻结记录写明合成人物只观察模拟平台推荐内容，不代表真实社交网络中的传播关系。",
    };
  }
  if (quote.includes("bounded projection") || quote.includes("hidden analysis")) {
    return {
      title: "支持“人物信息和提示词有明确边界”",
      body: "冻结记录限定了 Persona 使用的信息属性，并声明不包含隐藏分析指令。",
    };
  }
  if (quote.includes("observed actions only") || quote.includes("decision verdict")) {
    return {
      title: "支持“只记录动作，不推断现实结论”",
      body: "冻结记录只保存观察到的模拟动作，不据此推断立场、触达范围、现实预测或决策结论。",
    };
  }
  if (quote.includes("comment_count") || quote.includes("generated_post_count")) {
    return {
      title: "支持本次运行的动作计数",
      body: "这段冻结记录保存了起始内容、人物新增帖子、评论、反应和无动作等计数。",
    };
  }
  return {
    title: "本次冻结运行记录",
    body: "这段内容来自本次模拟的只读记录，用于支撑当前报告段落；可展开技术原文核对精确内容。",
  };
}

export function CitationDetails({
  citations,
}: {
  readonly citations: readonly CitationView[];
}): JSX.Element {
  return (
    <details className="citation-details">
      <summary>查看 {citations.length} 条支撑依据</summary>
      <ol>
        {citations.map((citation) => {
          const explanation = explainCitationForReader(citation);
          return (
            <li key={citation.position}>
              <header>
                <span>这条依据支持</span>
                <strong>{explanation.title}</strong>
              </header>
              <p>{explanation.body}</p>
              <details className="citation-technical-source">
                <summary>查看冻结技术原文</summary>
                <blockquote>{citation.quote}</blockquote>
                <footer>
                  <small>{formatCitationSourceLabel(citation.source_label)}</small>
                  <code>字符 {citation.start_offset}–{citation.end_offset}</code>
                </footer>
              </details>
            </li>
          );
        })}
      </ol>
    </details>
  );
}
