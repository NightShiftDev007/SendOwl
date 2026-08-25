import { useEffect, useMemo, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { ResearchPersonaInterviewPanel } from "./ResearchPersonaInterviewPanel";
import {
  createResearchProject,
  captureResearchProjectAgendaContext,
  createResearchRun,
  fetchResearchProjectAgendaContext,
  fetchResearchRunReport,
  previewResearchRunPlan,
  type ResearchProject,
  type ResearchProjectAgendaContext,
  type ResearchProjectCreateRequest,
  type ResearchRunCreateRequest,
  type ResearchRunReport,
  type ResearchSimulationPlan,
} from "./researchProjectContracts";
import { createNativeReportHash } from "./reportWorkspaceRoute";
import type { ResearchProjectRoute } from "./researchProjectRoute";
import { createRunStudioHash } from "./runStudioRoute";
import type { CohortSummary } from "./populationContracts";
import {
  formatProductResourceTitle,
  formatRunActionType,
  formatRunLimitation,
} from "./productPresentation";
import { useResearchProjects } from "./useResearchProjects";
import { useResearchRuns } from "./useResearchRuns";
import { useWorldModels, useWorldSnapshotDetail } from "./useWorldModels";
import { useSemanticWorldGraphs } from "./useSemanticWorldGraphs";
import { createWorldHash } from "./worldRoute";
import "./researchProjects.css";

function shortDigest(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

const runStatusLabel = {
  configured: "旧版配置",
  queued: "排队中",
  running: "模拟中",
  succeeded: "已完成",
  failed: "失败",
} as const;

const lifecycleLabel = {
  nascent: "刚出现",
  forming: "正在形成",
  confirmed: "已形成",
  evolving: "持续演变",
  archived: "已归档",
} as const;

function ProjectAgendaContext({ project }: { readonly project: ResearchProject }): JSX.Element {
  const [open, setOpen] = useState(false);
  const [context, setContext] = useState<ResearchProjectAgendaContext | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const load = async (): Promise<void> => {
    if (loading || loaded) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    try {
      setContext(await fetchResearchProjectAgendaContext(project.id, controller.signal));
      setLoaded(true);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught : new Error("读取议题上下文失败。"));
    } finally {
      setLoading(false);
    }
  };

  const toggle = (): void => {
    const next = !open;
    setOpen(next);
    if (next) void load();
  };

  const capture = async (): Promise<void> => {
    if (capturing) return;
    const controller = new AbortController();
    setCapturing(true);
    setError(null);
    try {
      setContext(await captureResearchProjectAgendaContext(project.id, controller.signal));
      setLoaded(true);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught : new Error("冻结议题上下文失败。"));
    } finally {
      setCapturing(false);
    }
  };

  const propagationCount = context?.payload.topics.reduce(
    (total, topic) => total + topic.propagation.length,
    0,
  ) ?? 0;
  const firstUtteranceCount = context?.payload.topics.reduce(
    (total, topic) => total + topic.first_utterances.length,
    0,
  ) ?? 0;

  return (
    <section className="research-project-agenda" aria-label="AgendaScope 议题上下文">
      <button type="button" aria-expanded={open} onClick={toggle}>
        <span>{open ? "收起" : "查看"} AgendaScope 议题上下文</span>
        <small>议题演变、跨地区传播与首次公开表述</small>
      </button>
      {open ? <div className="research-project-agenda-body">
        {loading ? <p role="status">正在读取已冻结的议题上下文…</p> : null}
        {error !== null ? <ApiErrorPanel title="无法读取议题上下文" error={error} isRetrying={false} onRetry={() => { setLoaded(false); void load(); }} /> : null}
        {loaded && context === null ? <div className="research-project-agenda-empty">
          <strong>这个历史项目还没有冻结 AgendaScope 议题上下文</strong>
          <p>可从项目已经绑定的现实快照补充冻结。该动作不调用模型，不会修改原快照、项目哈希或已有运行。</p>
          <button className="button button-secondary" type="button" disabled={capturing} onClick={() => { void capture(); }}>{capturing ? "正在冻结…" : "冻结当前议题上下文"}</button>
        </div> : null}
        {context !== null ? <>
          <div className="research-project-agenda-summary">
            <div><span>冻结报道</span><strong>{context.payload.frozen_article_ids.length} 篇</strong></div>
            <div><span>关联议题</span><strong>{context.payload.topics.length} 个</strong></div>
            <div><span>传播观察</span><strong>{propagationCount} 条</strong></div>
            <div><span>首次表述</span><strong>{firstUtteranceCount} 条</strong></div>
          </div>
          {context.payload.topics.length === 0 ? <p className="research-project-agenda-limited">该快照中的报道尚未关联 AgendaScope 已导入议题；系统保留真实的空结果，不会自动编造议题。</p> : <ol>
            {context.payload.topics.map((topic) => <li key={topic.id}>
              <header><strong>{topic.name}</strong><span>{lifecycleLabel[topic.lifecycle_state]}</span></header>
              {topic.summary !== null ? <p>{topic.summary}</p> : null}
              <dl><div><dt>关联报道</dt><dd>{topic.linked_article_ids.length} 篇</dd></div><div><dt>热度快照</dt><dd>{topic.salience.length} 个</dd></div><div><dt>传播事件</dt><dd>{topic.propagation.length} 条</dd></div><div><dt>首次表述</dt><dd>{topic.first_utterances.length} 条</dd></div></dl>
            </li>)}
          </ol>}
          <footer><span>冻结于 {new Date(context.captured_at).toLocaleString("zh-CN")}</span><code>{shortDigest(context.context_sha256)}</code></footer>
        </> : null}
      </div> : null}
    </section>
  );
}

export function ProjectRuns({
  project,
  cohorts,
  selectedRunId,
  onSelectRun,
}: {
  readonly project: ResearchProject;
  readonly cohorts: readonly CohortSummary[];
  readonly selectedRunId: string | null;
  readonly onSelectRun: ((runId: string) => void) | null;
}): JSX.Element {
  const runs = useResearchRuns(project.id);
  const [cohortId, setCohortId] = useState(project.legacy_design?.cohort.cohort_id ?? "");
  const [requirement, setRequirement] = useState(
    project.legacy_design?.simulation_requirement ?? "",
  );
  const [seed, setSeed] = useState(7);
  const [planningMode, setPlanningMode] = useState<"automatic" | "manual">("automatic");
  const [rounds, setRounds] = useState(1);
  const [minutesPerRound, setMinutesPerRound] = useState(60);
  const [timeHorizonMinutes, setTimeHorizonMinutes] = useState(1440);
  const [activityIntensity, setActivityIntensity] = useState<"low" | "standard" | "high">("standard");
  const [initialPost, setInitialPost] = useState("");
  const [scheduledPost, setScheduledPost] = useState("");
  const [scheduledOffsetMinutes, setScheduledOffsetMinutes] = useState(720);
  const [planPreview, setPlanPreview] = useState<ResearchSimulationPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [report, setReport] = useState<ResearchRunReport | null>(null);
  const [reportLoading, setReportLoading] = useState<string | null>(null);
  const reportRef = useRef<HTMLElement>(null);
  const selectedRunMissing = runs.state.status === "success"
    && selectedRunId !== null
    && !runs.state.data.items.some((run) => run.id === selectedRunId);

  useEffect(() => {
    if (report === null || reportRef.current === null) return;
    const frame = window.requestAnimationFrame(() => {
      const target = reportRef.current;
      if (target === null) return;
      target.scrollIntoView({
        block: "start",
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
      target.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [report]);

  const buildRequest = (): ResearchRunCreateRequest => ({
    cohort_id: cohortId,
    simulation_requirement: requirement,
    seed,
    planning_mode: planningMode,
    rounds: planningMode === "manual" ? rounds : null,
    minutes_per_round: planningMode === "manual" ? minutesPerRound : null,
    time_horizon_minutes: planningMode === "automatic" ? timeHorizonMinutes : null,
    activity_intensity: planningMode === "automatic" ? activityIntensity : null,
    initial_post: initialPost,
    scheduled_posts: scheduledPost.trim() === "" ? [] : [{
      content: scheduledPost,
      offset_minutes: scheduledOffsetMinutes,
    }],
  });

  const previewPlan = async (): Promise<void> => {
    if (cohortId === "" || requirement.trim() === "" || initialPost.trim() === "" || planLoading) return;
    const controller = new AbortController();
    setPlanLoading(true);
    setError(null);
    try {
      setPlanPreview(await previewResearchRunPlan(project.id, buildRequest(), controller.signal));
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught : new Error("生成运行编排预览失败。"));
    } finally {
      setPlanLoading(false);
    }
  };

  const enqueue = async (): Promise<void> => {
    if (
      cohortId === ""
      || requirement.trim() === ""
      || initialPost.trim() === ""
      || submitting
    ) return;
    const controller = new AbortController();
    setSubmitting(true);
    setError(null);
    try {
      await createResearchRun(
        project.id,
        buildRequest(),
        controller.signal,
      );
      setInitialPost("");
      setScheduledPost("");
      setPlanPreview(null);
      runs.reload();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught : new Error("加入模拟队列失败。"));
    } finally {
      setSubmitting(false);
    }
  };

  const openReport = async (runId: string): Promise<void> => {
    const controller = new AbortController();
    setReportLoading(runId);
    setError(null);
    try {
      setReport(await fetchResearchRunReport(project.id, runId, controller.signal));
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught : new Error("读取运行报告失败。"));
    } finally {
      setReportLoading(null);
    }
  };

  return (
    <div className="research-runs">
      {project.graph === null ? (
        <div className="research-runs-history-note" role="note">
          <strong>历史项目不再创建新运行</strong>
          <p>这个项目没有绑定语义图。下方已有运行仍可读取；请从成功语义图建立新项目后再运行。</p>
        </div>
      ) : <form onSubmit={(event) => { event.preventDefault(); void enqueue(); }}>
        <header>
          <div><strong>定义并启动一次独立模拟</strong><p>先绑定合成人群与本次模拟要求，再确认人物实际看到的起始内容。每次运行互相独立，不产生方案排名。</p></div>
          <span>会调用当前语义模型</span>
        </header>
        <div className="research-run-design">
          <label>模拟人群<select value={cohortId} required onChange={(event) => setCohortId(event.target.value)}><option value="">请选择合成人群</option>{cohorts.map((item) => <option value={item.id} key={item.id}>{formatProductResourceTitle(item.title)} · {item.persona_count} 人</option>)}</select></label>
          <label>本次模拟要求<textarea value={requirement} maxLength={4000} required rows={4} onChange={(event) => setRequirement(event.target.value)} placeholder="说明本次模拟要观察的问题、情境边界与停止条件。" /></label>
        </div>
        <label className="research-runs-initial">起始情境内容<textarea value={initialPost} maxLength={4000} required rows={4} onChange={(event) => setInitialPost(event.target.value)} placeholder="例如：虚构机构发布一则公开说明……这里填写 Persona 在模拟中实际看到的起始内容。" /></label>
        <fieldset className="research-runs-schedule">
          <legend>可选：定时追加一则合成更新</legend>
          <p>这条内容会在指定分钟进入模拟世界，始终标记为人工合成输入，不属于现实证据。</p>
          <label>追加内容<textarea value={scheduledPost} maxLength={4000} rows={3} onChange={(event) => { setScheduledPost(event.target.value); setPlanPreview(null); }} placeholder="例如：虚构机构在核验后补充一则进展说明……" /></label>
          <label>注入时间（分钟）<input type="number" min={15} max={2880} value={scheduledOffsetMinutes} onChange={(event) => { setScheduledOffsetMinutes(event.target.valueAsNumber); setPlanPreview(null); }} /></label>
        </fieldset>
        <div className="research-runs-settings">
          <label>随机种子<input type="number" min={0} max={2_147_483_647} value={seed} onChange={(event) => setSeed(event.target.valueAsNumber)} /></label>
          <label>编排方式<select value={planningMode} onChange={(event) => { setPlanningMode(event.target.value as "automatic" | "manual"); setPlanPreview(null); }}><option value="automatic">自动编排（可先预览）</option><option value="manual">手动设置轮次</option></select></label>
          {planningMode === "automatic" ? <>
            <label>观察时长<select value={timeHorizonMinutes} onChange={(event) => { setTimeHorizonMinutes(Number(event.target.value)); setPlanPreview(null); }}><option value={360}>6 小时</option><option value={720}>12 小时</option><option value={1440}>24 小时</option><option value={2880}>48 小时</option></select></label>
            <label>互动节奏<select value={activityIntensity} onChange={(event) => { setActivityIntensity(event.target.value as "low" | "standard" | "high"); setPlanPreview(null); }}><option value="low">低频</option><option value="standard">标准</option><option value="high">高频</option></select></label>
          </> : <>
            <label>轮数<select value={rounds} onChange={(event) => { setRounds(Number(event.target.value)); setPlanPreview(null); }}><option value={1}>1 轮</option><option value={2}>2 轮</option><option value={3}>3 轮</option><option value={4}>4 轮</option><option value={5}>5 轮</option><option value={6}>6 轮</option></select></label>
            <label>每轮时间<select value={minutesPerRound} onChange={(event) => { setMinutesPerRound(Number(event.target.value)); setPlanPreview(null); }}><option value={30}>30 分钟</option><option value={60}>60 分钟</option><option value={120}>120 分钟</option><option value={240}>240 分钟</option><option value={480}>480 分钟</option></select></label>
          </>}
          <button className="button" type="button" onClick={() => { void previewPlan(); }} disabled={cohortId === "" || requirement.trim() === "" || initialPost.trim() === "" || planLoading}>{planLoading ? "正在编排…" : "预览运行编排（不调用模型）"}</button>
          <button className="button button-primary" type="submit" disabled={cohortId === "" || requirement.trim() === "" || initialPost.trim() === "" || submitting}>{submitting ? "正在加入队列…" : "加入模拟队列"}</button>
        </div>
        {planPreview !== null ? <aside className="research-run-plan-preview" aria-live="polite"><strong>编排预览</strong><p>系统依据 {planPreview.context_item_count} 项冻结上下文与 {planPreview.persona_count} 名 Persona，编排为 {planPreview.rounds} 轮 × {planPreview.minutes_per_round} 分钟，共 {planPreview.horizon_minutes} 分钟；{planPreview.scheduled_posts.length} 条合成情境内容；平台固定为 Reddit。</p><ol>{planPreview.scheduled_posts.map((item) => <li key={item.position}>第 {item.offset_minutes} 分钟：{item.content}</li>)}</ol><p>只有点击“加入模拟队列”才会触发模型运行。</p></aside> : null}
      </form>}

      {error !== null ? <p className="research-projects-error" role="alert">{error.message}</p> : null}
      {runs.state.status === "error" ? <ApiErrorPanel title="无法读取模拟运行" error={runs.state.error} isRetrying={false} onRetry={runs.reload} /> : null}
      {runs.state.status === "loading" ? <p role="status">正在读取运行记录…</p> : null}
      {selectedRunMissing ? <p className="research-projects-error" role="alert">地址中的运行不属于当前研究项目，系统没有自动改选其他记录。</p> : null}
      {runs.state.status === "success" && runs.state.data.items.length === 0 ? <p className="research-runs-empty">尚未运行。确认起始情境后再加入队列；页面不会自动触发付费调用。</p> : null}
      {runs.state.status === "success" ? (
        <ul className="research-runs-list">
          {runs.state.data.items.map((run) => (
            <li key={run.id} data-selected={run.id === selectedRunId}>
              <div>
                <span className={`research-run-status is-${run.status}`}>{runStatusLabel[run.status]}</span>
                <strong>Seed {run.seed} · {run.rounds ?? "—"} 轮 · {run.cohort.persona_count} 人</strong>
                <code>{shortDigest(run.run_spec_sha256)}</code>
                {onSelectRun !== null ? <button className="research-run-select" type="button" aria-pressed={run.id === selectedRunId} onClick={() => onSelectRun(run.id)}>{run.id === selectedRunId ? "当前运行" : "聚焦此运行"}</button> : null}
              </div>
              <details open={run.id === selectedRunId ? true : undefined}>
                <summary>研究目的（不是 Persona 看到的内容）</summary>
                <p>{run.simulation_requirement}</p>
              </details>
              {run.initial_post !== null ? (
                <details className="research-run-initial-preview" open={run.id === selectedRunId ? true : undefined}>
                  <summary>Persona 看到的预置起始内容</summary>
                  <p>{run.initial_post}</p>
                </details>
              ) : null}
              {run.simulation_plan !== null ? (
                <details className="research-run-plan-record" open={run.id === selectedRunId ? true : undefined}>
                  <summary>已封存的运行编排与定时事件</summary>
                  <p>{run.simulation_plan.planning_mode === "automatic" ? "自动编排" : "手动编排"} · {run.simulation_plan.rounds} 轮 × {run.simulation_plan.minutes_per_round} 分钟 · {run.simulation_plan.activity_intensity === "manual" ? "手动节奏" : `${run.simulation_plan.activity_intensity} 节奏`} · Reddit</p>
                  <ol>{run.simulation_plan.scheduled_posts.map((item) => <li key={item.position}><strong>第 {item.offset_minutes} 分钟</strong><span>{item.content}</span></li>)}</ol>
                </details>
              ) : null}
              {run.simulation_context !== null ? (
                <details className="research-run-context-preview" open={run.id === selectedRunId ? true : undefined}>
                  <summary>Persona 同时收到的冻结现实上下文</summary>
                  <p>来自 {run.simulation_context.media_items.length} 篇媒体、{run.simulation_context.policy_items.length} 份政策、{run.simulation_context.nodes.length} 个实体和 {run.simulation_context.edges.length} 条关系。它用于理解背景，不等于现实预测。</p>
                  <ul>
                    {run.simulation_context.media_items.map((item) => <li key={item.article_id}><strong>{item.title}</strong><span>{item.source_name}：{item.excerpt}</span></li>)}
                    {run.simulation_context.nodes.map((item) => <li key={item.node_id}><strong>{item.name}</strong><span>{item.summary}</span></li>)}
                  </ul>
                </details>
              ) : null}
              {run.result !== null ? <dl><div><dt>预置起始内容</dt><dd>{run.result.initial_post_count}</dd></div><div><dt>人物新增帖子</dt><dd>{run.result.generated_post_count}</dd></div><div><dt>评论</dt><dd>{run.result.comment_count}</dd></div><div><dt>反应</dt><dd>{run.result.reaction_count}</dd></div><div><dt>未采取动作</dt><dd>{run.result.do_nothing_count}</dd></div></dl> : null}
              {run.error !== null ? <p className="research-run-failure">{run.error.message}</p> : null}
              {run.status === "succeeded" ? (
                <div className="research-run-actions">
                  <button type="button" onClick={() => { void openReport(run.id); }} disabled={reportLoading === run.id}>{reportLoading === run.id ? "正在读取…" : report?.run.id === run.id ? "已在下方展开运行记录" : "查看冻结运行记录"}</button>
                  <a href={createNativeReportHash(project.id, run.id)}>打开研究报告与追问</a>
                  {report?.run.id === run.id ? <span role="status">运行记录已在下方展开并定位</span> : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {report !== null ? <section ref={reportRef} tabIndex={-1} className="research-run-report" aria-label="冻结运行记录" aria-live="polite"><header><div><span>已封存的单次运行记录</span><h3>本次模拟输入与事件</h3></div><button type="button" onClick={() => setReport(null)}>关闭</button></header><article><h4>现实证据边界</h4><p>本次运行绑定冻结现实快照 <code>{shortDigest(report.research_project.snapshot.snapshot_sha256)}</code>。现实证据只用于固定研究背景，不代表对现实事实作出裁决。</p>{report.run.simulation_context !== null ? <p>Persona 提示词同时绑定 {report.run.simulation_context.media_items.length} 篇媒体、{report.run.simulation_context.policy_items.length} 份政策、{report.run.simulation_context.nodes.length} 个实体和 {report.run.simulation_context.edges.length} 条关系。</p> : <p>这是历史运行，未绑定可展示的语义图上下文。</p>}</article><article><h4>研究目的</h4><strong>{report.research_project.research_question}</strong><p>{report.run.simulation_requirement}</p></article><article><h4>Persona 看到的合成情境内容</h4>{report.run.simulation_plan !== null ? <ol>{report.run.simulation_plan.scheduled_posts.map((item) => <li key={item.position}><strong>第 {item.offset_minutes} 分钟</strong><blockquote>{item.content}</blockquote></li>)}</ol> : <blockquote>{report.run.initial_post}</blockquote>}<p>这些内容由实验预先放入，不是现实报道，也不是 Persona 生成的帖子。</p></article><article><h4>本轮动作计数</h4><p>预置情境帖子 {report.run.result?.initial_post_count ?? 0}、人物新增帖子 {report.run.result?.generated_post_count ?? 0}、评论 {report.run.result?.comment_count ?? 0}、反应 {report.run.result?.reaction_count ?? 0}、未采取动作 {report.run.result?.do_nothing_count ?? 0}。</p></article><article><h4>事件明细</h4><ol>{report.events.map((event) => <li key={event.sequence}><span>#{event.sequence} · 第 {event.round} 轮 · {event.actor_kind === "scenario" ? "实验预置" : "合成人物"} · {formatRunActionType(event.action_type)}</span>{event.content !== null ? <p>{event.content}</p> : null}</li>)}</ol></article>{report.graph_memory.length > 0 ? <article><h4>运行世界记忆</h4><p>系统在每轮结束后，把已经发生的人物、帖子、评论与动作关系封存为可校验图快照；它只重组已记录事件，不推断新事实。</p><ol>{report.graph_memory.map((memory) => <li key={memory.round}>第 {memory.round} 轮：累计 {memory.cumulative_event_count} 个事件、{memory.nodes.length} 个节点、{memory.edges.length} 条关系。</li>)}</ol></article> : null}{report.run.schema_version === "sandowl-research-simulation-run/v4" && report.graph_memory.length > 0 ? <ResearchPersonaInterviewPanel projectId={report.research_project.id} runId={report.run.id} cohortId={report.run.cohort.cohort_id} /> : null}<article><h4>适用边界</h4><ul>{report.run.result?.limitations.map((item) => <li key={item}>{formatRunLimitation(item)}</li>)}</ul><p>所有结果仅描述这一次合成运行，不构成现实预测、商业建议或方案比较。</p></article></section> : null}
    </div>
  );
}

export function ResearchProjectsPage({
  route,
  onRouteChange,
}: {
  readonly route: ResearchProjectRoute;
  readonly onRouteChange: (route: ResearchProjectRoute) => void;
}): JSX.Element {
  const projects = useResearchProjects();
  const worldModels = useWorldModels();
  const selectedSnapshot = useWorldSnapshotDetail(route.worldModelId, route.snapshotId);
  const semanticGraphs = useSemanticWorldGraphs(route.worldModelId, route.snapshotId);
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<Error | null>(null);

  const selectedModel = useMemo(
    () => worldModels.state.data?.items.find((item) => item.id === route.worldModelId) ?? null,
    [route.worldModelId, worldModels.state],
  );
  const snapshot = selectedSnapshot.state.status === "idle"
    ? null
    : selectedSnapshot.state.data?.id === route.snapshotId
      && selectedSnapshot.state.data.world_model_id === route.worldModelId
      ? selectedSnapshot.state.data
      : null;
  const succeededGraphs = useMemo(
    () => semanticGraphs.state.data?.items.filter((item) => item.status === "succeeded") ?? [],
    [semanticGraphs.state.data],
  );
  const graph = succeededGraphs.find(
    (item) => item.id === route.graphId && item.status === "succeeded",
  ) ?? null;
  const graphIsPending = semanticGraphs.state.data?.items.some(
    (item) => item.status === "queued" || item.status === "running",
  ) ?? false;
  const canSubmit = title.trim() !== ""
    && question.trim() !== ""
    && selectedModel !== null
    && snapshot !== null
    && graph !== null
    && !submitting;

  useEffect(() => {
    const submittedGraphId = semanticGraphs.selectedGraphId;
    if (
      submittedGraphId === null
      || route.graphId !== null
      || !succeededGraphs.some((item) => item.id === submittedGraphId)
    ) {
      return;
    }
    onRouteChange({ ...route, graphId: submittedGraphId });
  }, [onRouteChange, route, semanticGraphs.selectedGraphId, succeededGraphs]);

  const selectWorldModel = (worldModelId: string): void => {
    if (worldModelId === "") {
      onRouteChange({ worldModelId: null, snapshotId: null, graphId: null });
      return;
    }
    const worldModel = worldModels.state.data?.items.find((item) => item.id === worldModelId);
    if (worldModel === undefined) {
      throw new Error("Cannot select a WorldModel that is absent from the loaded directory.");
    }
    onRouteChange({ worldModelId, snapshotId: worldModel.latest_snapshot.id, graphId: null });
  };

  const submit = async (): Promise<void> => {
    if (!canSubmit || selectedModel === null || snapshot === null) return;
    const controller = new AbortController();
    const request: ResearchProjectCreateRequest = {
      title,
      research_question: question,
      world_model_id: selectedModel.id,
      world_snapshot_id: snapshot.id,
      world_graph_id: graph.id,
    };
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createResearchProject(request, controller.signal);
      setTitle("");
      setQuestion("");
      projects.reload();
    } catch (error: unknown) {
      setSubmitError(error instanceof Error ? error : new Error("创建研究项目失败。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="research-projects-page" aria-labelledby="research-projects-title">
      <header className="research-projects-hero">
        <div>
          <span>媒体证据 → Project / Graph 上下文</span>
          <h1 id="research-projects-title">研究项目</h1>
          <p>先把研究问题与冻结证据封存为 Project / Graph 上下文。合成人群和 simulation requirement 在下一阶段按单次运行绑定。</p>
        </div>
        <aside>
          <strong>研究边界</strong>
          <p>模拟结果只描述合成人物在设定情境中的动作，不代表现实预测、真人研究或行动建议。</p>
        </aside>
      </header>

      <div className="research-projects-layout">
        <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <header><span>新建研究项目</span><h2>建立研究上下文</h2></header>
          {route.worldModelId === null || route.snapshotId === null ? (
            <div className="research-project-source is-empty">
              <div><strong>还没有带入冻结现实</strong><p>可从这里选择某个模型的最新快照，或先回到现实版本室核验并锁定历史版本。</p></div>
              <a href="#/world">前往现实版本室</a>
            </div>
          ) : (
            <div className="research-project-source" aria-live="polite">
              <div>
                <span>冻结现实已带入</span>
                <strong>{selectedModel === null ? "正在核验 WorldModel…" : formatProductResourceTitle(selectedModel.title)}</strong>
                <p>{snapshot === null ? "正在读取指定快照；系统不会自动改选其他版本。" : `已锁定 v${snapshot.version} · ${shortDigest(snapshot.snapshot_sha256)}`}</p>
              </div>
              <a href={createWorldHash({ worldModelId: route.worldModelId, snapshotId: route.snapshotId, evidenceId: null })}>返回核验证据</a>
            </div>
          )}
          <label>项目标题<input value={title} maxLength={300} required onChange={(event) => setTitle(event.target.value)} placeholder="例如：公共事件中的信息传播观察" /></label>
          <label>研究问题<textarea value={question} maxLength={2000} required rows={3} onChange={(event) => setQuestion(event.target.value)} placeholder="这次合成模拟希望观察什么？" /></label>
          <label>冻结证据<select value={route.worldModelId ?? ""} required onChange={(event) => selectWorldModel(event.target.value)}><option value="">请选择世界快照</option>{worldModels.state.data?.items.map((item) => <option value={item.id} key={item.id}>{formatProductResourceTitle(item.title)} · {item.id === route.worldModelId && snapshot !== null ? `第 ${snapshot.version} 版` : `最新第 ${item.latest_snapshot.version} 版`}</option>)}</select><small>从下拉列表切换模型时会明确选择该模型的最新快照；从现实版本室进入时保留你选定的精确版本。</small></label>
          <label>语义图<select value={route.graphId ?? ""} required disabled={snapshot === null} onChange={(event) => onRouteChange({ ...route, graphId: event.target.value === "" ? null : event.target.value })}><option value="">请选择已校验语义图</option>{succeededGraphs.map((item) => <option value={item.id} key={item.id}>{new Date(item.completed_at ?? item.created_at).toLocaleString("zh-CN")} · {item.nodes.length} 个实体 / {item.edges.length} 条关系</option>)}</select><small>项目会绑定这张图的完整身份与哈希，后续运行不会自动改用新图。</small></label>
          {snapshot !== null && semanticGraphs.state.status !== "error" && succeededGraphs.length === 0 ? (
            <div className="research-project-graph-empty" role="status" aria-live="polite">
              <div>
                <strong>{graphIsPending ? "语义图正在生成" : "当前快照还没有已校验语义图"}</strong>
                <p>{graphIsPending
                  ? "任务完成后会自动选中本次生成的图，再开放项目创建。"
                  : "先从当前冻结快照提取一次关系图。该操作不会修改快照；成功后会自动选中结果。"}</p>
              </div>
              <button
                className="button button-secondary"
                type="button"
                disabled={graphIsPending || semanticGraphs.enqueueState === "submitting"}
                onClick={() => { void semanticGraphs.enqueue(); }}
              >
                {semanticGraphs.enqueueState === "submitting" ? "正在提交…" : graphIsPending ? "等待图谱完成…" : "生成当前快照的语义图"}
              </button>
            </div>
          ) : null}
          {worldModels.state.status === "error" ? <ApiErrorPanel title="无法读取冻结证据" error={worldModels.state.error} isRetrying={worldModels.state.isRetrying} onRetry={worldModels.reload} /> : null}
          {selectedSnapshot.state.status === "error" ? <ApiErrorPanel title="无法读取指定的冻结快照" error={selectedSnapshot.state.error} isRetrying={selectedSnapshot.state.isRetrying} onRetry={selectedSnapshot.reload} /> : null}
          {semanticGraphs.state.status === "error" ? <ApiErrorPanel title="无法读取语义图" error={semanticGraphs.state.error} isRetrying={semanticGraphs.state.isRetrying} onRetry={semanticGraphs.reload} /> : null}
          {submitError !== null ? <p className="research-projects-error" role="alert">{submitError.message}</p> : null}
          <button className="button button-primary" type="submit" disabled={!canSubmit}>{submitting ? "正在创建…" : "创建研究项目"}</button>
        </form>

        <div className="research-projects-directory">
          <header><div><span>研究项目目录</span><h2>已有研究项目</h2></div><button type="button" onClick={projects.reload}>刷新</button></header>
          {projects.state.status === "loading" ? <p role="status">正在读取研究项目…</p> : null}
          {projects.state.status === "error" ? <ApiErrorPanel title="无法读取研究项目" error={projects.state.error} isRetrying={false} onRetry={projects.reload} /> : null}
          {projects.state.status === "success" && projects.state.data.items.length === 0 ? <div className="research-projects-empty"><strong>还没有研究项目</strong><p>先从左侧选择冻结证据并写明研究问题，建立可继续设计模拟的 Project / Graph 上下文。</p></div> : null}
          {projects.state.status === "success" ? <ol>{projects.state.data.items.map((project) => <li key={project.id}><header><strong>{formatProductResourceTitle(project.title)}</strong><time>{new Date(project.created_at).toLocaleString("zh-CN")}</time></header><div className="research-project-boundaries"><section><span>现实证据</span><strong>已冻结，可回到媒体或政策原文</strong><p>只固定研究背景，不等于系统已经裁决事实。</p></section><section><span>语义图</span><strong>{project.graph === null ? "历史项目未绑定" : `${project.graph.node_count} 个实体 / ${project.graph.edge_count} 条关系`}</strong><p>{project.graph === null ? "可读取已有结果，但不能再创建未携带图谱上下文的新运行。" : "运行会冻结其中进入 Persona 提示词的有界上下文。"}</p></section><section><span>研究问题</span><p>{project.research_question}</p></section></div><dl><div><dt>证据快照</dt><dd><code>{shortDigest(project.snapshot.snapshot_sha256)}</code></dd></div><div><dt>项目哈希</dt><dd><code>{shortDigest(project.project_sha256)}</code></dd></div><div><dt>上下文版本</dt><dd>{project.schema_version.endsWith("/v3") ? "图谱绑定" : "历史兼容"}</dd></div></dl><ProjectAgendaContext project={project} /><div className="research-project-handoff"><div><strong>{project.graph === null ? "历史项目只读" : "下一步：准备人群并定义单次模拟"}</strong><p>{project.graph === null ? "已有运行和报告保持可读；新运行请从语义图重新建立 v3 项目。" : "需要新建或核验 Cohort 时先进入“模拟人群”；已有合适人群可直接进入模拟运行。本页不会自动创建运行。"}</p></div><div className="research-project-handoff-actions"><a className="button button-secondary" href={createWorldHash({ worldModelId: project.snapshot.world_model_id, snapshotId: project.snapshot.world_snapshot_id, evidenceId: null })}>查看现实证据与原文</a><a className="button button-secondary" href="#/personas">准备模拟人群</a>{project.graph !== null ? <a className="button button-primary" href={createRunStudioHash({ mode: "native", projectId: project.id, runId: null })}>进入模拟运行</a> : null}</div></div></li>)}</ol> : null}
        </div>
      </div>
    </section>
  );
}
