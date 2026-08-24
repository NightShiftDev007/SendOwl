import { useCallback, useEffect, useMemo, useState } from "react";

import { AgentInteractionPanel } from "./AgentInteractionPanel";
import { ApiErrorPanel } from "./ApiErrorPanel";
import { CitationDetails } from "./CitationDetails";
import {
  createResearchRunReportAgent,
  enqueueReportAgentDraft,
  fetchReportAgentDraft,
  fetchResearchRunReportAgent,
  listReportAgentDrafts,
  retryReportAgentDraft,
  type ReportAgentCitedDraft,
} from "./reportAgentContracts";
import { createLegacyReportHash, createNativeReportHash } from "./reportWorkspaceRoute";
import {
  fetchResearchRunReport,
  fetchResearchRunReports,
  type ResearchRunReport,
  type ResearchRunReportSummary,
  type ResearchRunReportsResponse,
} from "./researchProjectContracts";
import {
  buildResearchReportReaderSummary,
  formatReportBodyForReader,
  formatProductResourceTitle,
  formatRunActionType,
  formatRunLimitation,
} from "./productPresentation";
import { createRunStudioHash } from "./runStudioRoute";
import { createWorldHash } from "./worldRoute";
import "./researchReports.css";

type DirectoryState =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly error: Error }
  | { readonly status: "success"; readonly data: ResearchRunReportsResponse };

function asError(error: unknown, message: string): Error {
  return error instanceof Error ? error : new Error(message);
}

function shortDigest(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString("zh-CN");
}

const draftStatusLabels: Readonly<Record<ReportAgentCitedDraft["status"], string>> = {
  queued: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
};

export function ResearchReportsPage({
  initialProjectId,
  initialRunId,
}: {
  readonly initialProjectId: string | null;
  readonly initialRunId: string | null;
}): JSX.Element {
  const [directory, setDirectory] = useState<DirectoryState>({ status: "loading" });
  const [report, setReport] = useState<ResearchRunReport | null>(null);
  const [draft, setDraft] = useState<ReportAgentCitedDraft | null>(null);
  const [loadingReport, setLoadingReport] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<Error | null>(null);

  const loadDirectory = useCallback((): (() => void) => {
    const controller = new AbortController();
    setDirectory({ status: "loading" });
    void fetchResearchRunReports(controller.signal)
      .then((data) => setDirectory({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setDirectory({ status: "error", error: asError(error, "读取原生报告目录失败。") });
      });
    return () => controller.abort();
  }, []);

  useEffect(
    () => loadDirectory(),
    [initialProjectId, initialRunId, loadDirectory],
  );

  const selectedSummary = useMemo<ResearchRunReportSummary | null>(() => {
    if (
      directory.status !== "success"
      || initialProjectId === null
      || initialRunId === null
    ) return null;
    return directory.data.items.find(
      (item) => item.research_project.id === initialProjectId && item.run.id === initialRunId,
    ) ?? null;
  }, [directory, initialProjectId, initialRunId]);
  const readerSummary = useMemo(
    () => report === null ? null : buildResearchReportReaderSummary(report),
    [report],
  );

  useEffect(() => {
    if (initialProjectId === null || initialRunId === null || directory.status !== "success") {
      setReport(null);
      setDraft(null);
      setWorkspaceError(null);
      return;
    }
    if (selectedSummary === null) {
      setReport(null);
      setDraft(null);
      setWorkspaceError(new Error("报告目录中不存在这个 Project / Simulation Run 组合。"));
      return;
    }
    const controller = new AbortController();
    setLoadingReport(true);
    setWorkspaceError(null);
    setReport(null);
    setDraft(null);
    void Promise.all([
      fetchResearchRunReport(initialProjectId, initialRunId, controller.signal),
      fetchResearchRunReportAgent(initialProjectId, initialRunId, controller.signal),
    ]).then(async ([loadedReport, agentRun]) => {
      setReport(loadedReport);
      if (agentRun === null) return;
      const drafts = await listReportAgentDrafts(agentRun.id, controller.signal);
      setDraft(drafts.items.at(-1) ?? null);
    }).catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setWorkspaceError(asError(error, "读取单次运行报告失败。"));
    }).finally(() => setLoadingReport(false));
    return () => controller.abort();
  }, [directory.status, initialProjectId, initialRunId, selectedSummary]);

  useEffect(() => {
    if (draft === null || (draft.status !== "queued" && draft.status !== "running")) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void fetchReportAgentDraft(draft.id, controller.signal)
        .then(setDraft)
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setWorkspaceError(asError(error, "刷新 ReportAgent 报告状态失败。"));
        });
    }, 1_500);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [draft]);

  const generateReport = async (): Promise<void> => {
    if (initialProjectId === null || initialRunId === null || generating) return;
    const controller = new AbortController();
    setGenerating(true);
    setWorkspaceError(null);
    try {
      const agentRun = await createResearchRunReportAgent(
        initialProjectId,
        initialRunId,
        controller.signal,
      );
      setDraft(await enqueueReportAgentDraft(agentRun.id, controller.signal));
    } catch (error: unknown) {
      setWorkspaceError(asError(error, "生成 ReportAgent 报告失败。"));
    } finally {
      setGenerating(false);
    }
  };

  const retryDraft = async (): Promise<void> => {
    if (draft === null || draft.status !== "failed" || draft.attempt_number >= 5 || generating) return;
    const controller = new AbortController();
    setGenerating(true);
    setWorkspaceError(null);
    try {
      setDraft(await retryReportAgentDraft(draft.id, controller.signal));
    } catch (error: unknown) {
      setWorkspaceError(asError(error, "重试 ReportAgent 报告失败。"));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <section className="research-reports-page" aria-labelledby="research-reports-title">
      <header className="research-reports-hero">
        <div>
          <span>单次模拟运行 → 研究报告 → 继续追问</span>
          <h1 id="research-reports-title">报告与交互</h1>
          <p>先阅读本轮观察与适用边界，再按需查看冻结来源、技术审计或继续追问。</p>
        </div>
      </header>

      <aside className="research-reports-boundary">
        <strong>阅读说明</strong>
        <p>默认报告面向研究阅读；哈希、资源 ID、运行配置和英文原始片段统一收入“技术审计”。合成观察始终不等于现实预测。</p>
      </aside>

      <ol className="research-report-flow" aria-label="报告工作进度">
        <li data-state={initialProjectId === null ? "pending" : "complete"}><span>1</span><div><strong>研究项目</strong><small>{initialProjectId === null ? "等待选择报告" : "已绑定"}</small></div></li>
        <li data-state={initialRunId === null ? "pending" : "complete"}><span>2</span><div><strong>模拟运行</strong><small>{initialRunId === null ? "等待选择报告" : "已封存"}</small></div></li>
        <li data-state={report === null ? "pending" : "complete"}><span>3</span><div><strong>冻结报告</strong><small>{report === null ? "等待读取" : "已核验"}</small></div></li>
        <li data-state={draft?.status === "succeeded" ? "complete" : draft === null ? "pending" : "current"}><span>4</span><div><strong>引用报告与追问</strong><small>{draft === null ? "按需生成" : draftStatusLabels[draft.status]}</small></div></li>
      </ol>

      {directory.status === "loading" ? <div className="research-reports-skeleton" role="status">正在读取单次运行报告…</div> : null}
      {directory.status === "error" ? <ApiErrorPanel title="无法读取报告目录" error={directory.error} isRetrying={false} onRetry={loadDirectory} /> : null}
      {workspaceError !== null ? <p className="research-reports-error" role="alert">{workspaceError.message}</p> : null}

      {directory.status === "success" && directory.data.items.length === 0 ? (
        <section className="research-reports-empty">
          <strong>还没有原生单次运行报告</strong>
          <p>先在“模拟运行”中选择研究项目并完成一次独立模拟。运行成功并封存后，报告会自动出现在这里。</p>
          <div className="research-reports-empty-actions">
            <button className="button button-secondary" type="button" onClick={loadDirectory}>刷新报告目录</button>
            <a className="button button-primary" href="#/runs">前往模拟运行</a>
          </div>
        </section>
      ) : null}

      {directory.status === "success" && directory.data.items.length > 0 ? (
        <div className="research-reports-layout">
          <section className="research-reports-directory" aria-labelledby="report-directory-title">
            <header>
              <div><span>{directory.data.total} 份封存记录</span><h2 id="report-directory-title">单次运行报告</h2></div>
              <button type="button" onClick={loadDirectory}>刷新</button>
            </header>
            <ol>
              {directory.data.items.map((item) => {
                const selected = item.run.id === initialRunId
                  && item.research_project.id === initialProjectId;
                return (
                  <li key={item.id} data-selected={selected}>
                    <a href={createNativeReportHash(item.research_project.id, item.run.id)} aria-current={selected ? "page" : undefined}>
                      <span>{formatDate(item.created_at)}</span>
                      <strong>{formatProductResourceTitle(item.research_project.title)}</strong>
                      <p>{item.research_project.research_question}</p>
                      <dl>
                        <div><dt>人物</dt><dd>{item.run.cohort.persona_count}</dd></div>
                        <div><dt>事件</dt><dd>{item.run.result?.observed_action_count ?? 0}</dd></div>
                        <div><dt>Seed</dt><dd>{item.run.seed}</dd></div>
                      </dl>
                      <code>{shortDigest(item.report_sha256)}</code>
                    </a>
                  </li>
                );
              })}
            </ol>
          </section>

          <section className="research-report-workspace" aria-live="polite">
            {initialRunId === null ? (
              <div className="research-report-placeholder">
                <span>选择一份报告</span>
                <h2>查看冻结记录、生成引用报告并继续追问</h2>
                <p>打开目录中的单次运行报告。读取不会调用模型；只有明确点击生成或追问才会产生模型任务。</p>
              </div>
            ) : null}
            {loadingReport ? <div className="research-reports-skeleton" role="status">正在核验报告与引用状态…</div> : null}
            {report !== null ? (
              <>
                <header className="research-report-toolbar">
                  <div><span>已封存 · 单次合成观察</span><h2>{formatProductResourceTitle(report.research_project.title)}</h2></div>
                  <nav aria-label="当前报告操作"><a href={createRunStudioHash({ mode: "native", projectId: report.research_project.id, runId: report.run.id })}>返回对应模拟运行</a><a href="#/reports">关闭报告</a></nav>
                </header>
                {readerSummary !== null ? (
                  <article className="research-report-reader">
                    <section className="research-report-reader-summary" aria-labelledby="reader-summary-title">
                      <span>本轮观察摘要</span>
                      <h3 id="reader-summary-title">{readerSummary.headline}</h3>
                      <p>{readerSummary.detail}</p>
                      <div className="research-report-reader-boundaries">
                        <section><h4>这份报告能说明</h4><ul>{readerSummary.canSay.map((item) => <li key={item}>{item}</li>)}</ul></section>
                        <section><h4>这份报告不能说明</h4><ul>{readerSummary.cannotSay.map((item) => <li key={item}>{item}</li>)}</ul></section>
                      </div>
                    </section>

                    <section className="research-report-reader-context">
                      <header><span>研究问题与输入边界</span><h3>{report.research_project.research_question}</h3></header>
                      <div>
                        <section>
                          <strong>现实背景证据</strong>
                          <p>来自人工选择并冻结的媒体或政策来源，只用于固定研究发生的现实背景。</p>
                          {report.run.simulation_context !== null ? (
                            <details className="research-report-context-details">
                              <summary>查看 Persona 实际收到的背景摘要</summary>
                              <p>本次输入包含 {report.run.simulation_context.media_items.length} 篇媒体、{report.run.simulation_context.policy_items.length} 份政策、{report.run.simulation_context.nodes.length} 个实体和 {report.run.simulation_context.edges.length} 条关系。</p>
                              <ul>{report.run.simulation_context.media_items.map((item) => <li key={item.article_id}><strong>{item.title}</strong><span>{item.source_name}：{item.excerpt}</span></li>)}</ul>
                            </details>
                          ) : <small>这是历史运行；当时只绑定了快照身份，没有把语义图摘要传入 Persona。</small>}
                          <a href={createWorldHash({ worldModelId: report.research_project.snapshot.world_model_id, snapshotId: report.research_project.snapshot.world_snapshot_id, evidenceId: null })}>查看冻结来源与原文</a>
                        </section>
                        <section>
                          <strong>合成模拟输入</strong>
                          <p>{report.run.initial_post}</p>
                          <small>这段内容是本次实验预置给 Persona 看到的虚构情境，不是现实报道，也不是 Persona 生成的帖子。</small>
                        </section>
                      </div>
                    </section>

                    <section className="research-report-reader-observations">
                      <header><span>本轮行为记录</span><h3>合成人物实际留下了哪些动作</h3></header>
                      <dl>
                        <div><dt>预置起始内容</dt><dd>{report.run.result?.initial_post_count ?? 0}</dd><small>由实验预先放入</small></div>
                        <div><dt>人物新增帖子</dt><dd>{report.run.result?.generated_post_count ?? 0}</dd><small>由 Persona 生成</small></div>
                        <div><dt>评论</dt><dd>{report.run.result?.comment_count ?? 0}</dd><small>人物可见动作</small></div>
                        <div><dt>反应</dt><dd>{report.run.result?.reaction_count ?? 0}</dd><small>点赞或点踩</small></div>
                        <div><dt>未采取动作</dt><dd>{report.run.result?.do_nothing_count ?? 0}</dd><small>本轮保持沉默</small></div>
                      </dl>
                      <details className="research-report-event-log">
                        <summary>查看 {report.events.length} 条事件明细</summary>
                        <ol>{report.events.map((event) => <li key={event.sequence}><span>#{event.sequence} · 第 {event.round} 轮 · {event.actor_kind === "scenario" ? "实验预置" : "合成人物"} · {formatRunActionType(event.action_type)}</span>{event.content !== null ? <p>{event.content}</p> : null}</li>)}</ol>
                      </details>
                    </section>
                  </article>
                ) : null}

                <section className="research-report-agent" aria-labelledby="report-agent-title">
                  <header><div><span>多来源用户报告</span><h2 id="report-agent-title">把证据、图谱、模拟与 Persona 追问连成一份报告</h2></div>{draft === null ? <button className="button button-primary" type="button" disabled={generating} onClick={() => { void generateReport(); }}>{generating ? "正在提交…" : "生成用户报告（调用模型）"}</button> : null}</header>
                  {draft === null ? <p>当前已经可以阅读本轮观察；如需完整叙事，可明确调用模型同时读取冻结现实证据、语义图、单次运行，以及本轮已获授权的 Persona 追问。每个章节都会显示它实际依赖的来源。</p> : null}
                  {draft !== null ? <p>生成尝试 {draft.attempt_number} / 5 · {draftStatusLabels[draft.status]}</p> : null}
                  {draft?.status === "queued" || draft?.status === "running" ? <p role="status">报告助手正在整理多来源材料并核验逐章引用…</p> : null}
                  {draft?.status === "failed" ? (
                    <div>
                      <p className="research-reports-error" role="alert">{draft.error_message}</p>
                      <button className="button button-primary" type="button" disabled={generating || draft.attempt_number >= 5} onClick={() => { void retryDraft(); }}>
                        {generating ? "正在提交…" : "保留失败并重试（调用模型）"}
                      </button>
                    </div>
                  ) : null}
                  {draft?.status === "succeeded" ? (
                    <>
                      <p>这份草稿只反映生成时已经存在并获授权的材料；之后新增的 Persona 访谈不会回写已封存草稿。</p>
                      <article className="research-report-narrative">
                        <header><span>面向读者 · 逐章可追溯</span><h3>{draft.title}</h3></header>
                        {draft.sections.map((section) => <section key={section.position}><h4>{section.title}</h4><p>{formatReportBodyForReader(section.body_markdown)}</p><CitationDetails citations={section.citations} /></section>)}
                        <details className="research-report-draft-identity"><summary>查看辅助解读的技术身份</summary><dl><div><dt>ReportAgent 草稿 ID</dt><dd><code>{draft.id}</code></dd></div><div><dt>草稿 SHA-256</dt><dd><code>{draft.draft_sha256}</code></dd></div></dl></details>
                      </article>
                      <AgentInteractionPanel draftId={draft.id} />
                    </>
                  ) : null}
                </section>

                <details className="research-report-audit">
                  <summary>技术审计：运行配置、限制与资源哈希</summary>
                  <div className="research-report-audit-body">
                    <section><h3>运行配置</h3><p>Seed {report.run.seed}；{report.run.rounds} 轮；每轮 {report.run.minutes_per_round} 分钟；{report.run.cohort.persona_count} 个合成人物。</p><p>{report.run.simulation_requirement}</p></section>
                    <section><h3>运行限制</h3><ul>{report.run.result?.limitations.map((item) => <li key={item}>{formatRunLimitation(item)}</li>)}</ul></section>
                    <section><h3>完整资源身份</h3><dl className="research-report-identities"><div><dt>冻结现实快照</dt><dd><span>资源 ID</span><code>{report.research_project.snapshot.world_snapshot_id}</code><span>SHA-256</span><code>{report.research_project.snapshot.snapshot_sha256}</code></dd></div>{report.research_project.graph !== null ? <div><dt>语义图</dt><dd><span>资源 ID</span><code>{report.research_project.graph.graph_id}</code><span>SHA-256</span><code>{report.research_project.graph.graph_sha256}</code></dd></div> : null}<div><dt>研究项目</dt><dd><span>资源 ID</span><code>{report.research_project.id}</code><span>SHA-256</span><code>{report.research_project.project_sha256}</code></dd></div><div><dt>模拟人群</dt><dd><span>资源 ID</span><code>{report.run.cohort.cohort_id}</code><span>SHA-256</span><code>{report.run.cohort.cohort_sha256}</code></dd></div><div><dt>模拟运行</dt><dd><span>资源 ID</span><code>{report.run.id}</code><span>SHA-256</span><code>{report.run.run_spec_sha256}</code>{report.run.simulation_context_sha256 !== null ? <><span>上下文 SHA-256</span><code>{report.run.simulation_context_sha256}</code></> : null}</dd></div><div><dt>单次运行报告</dt><dd><span>资源 ID</span><code>{report.id}</code><span>SHA-256</span><code>{report.report_sha256}</code></dd></div></dl></section>
                  </div>
                </details>

                <aside className="research-evaluation-handoff">
                  <div><strong>需要额外能力评测？</strong><p>进入当前 Project / Run / Cohort 的评测中心。系统会明确标出哪些任务已经原生绑定，哪些仍只是独立样例；评测不会自动给模拟结论打分。</p></div>
                  <a className="button button-secondary" href={`#/tasks?project_id=${encodeURIComponent(report.research_project.id)}&run_id=${encodeURIComponent(report.run.id)}`}>打开当前研究评测中心</a>
                </aside>
                <details className="research-legacy-reports">
                  <summary>历史兼容报告</summary>
                  <p>这里只为回查旧多方案数据保留只读入口；它不属于当前 SandOwl 单次模拟工作流。</p>
                  <a href={createLegacyReportHash(null)}>打开历史多方案归档（只读）</a>
                </details>
              </>
            ) : null}
          </section>
        </div>
      ) : null}
    </section>
  );
}
