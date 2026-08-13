import { useMemo, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import type { DecisionThreadContextRequest } from "./decisionThreadContracts";
import { useCohorts } from "./usePopulations";
import { useScenarios } from "./useScenarios";
import { useSemanticExperiments } from "./useSemanticExperiments";
import { useDecisionThreads } from "./useDecisionThreads";
import "./decisionThreads.css";

function shortDigest(value: string | null): string {
  return value === null ? "—" : `${value.slice(0, 10)}…${value.slice(-6)}`;
}

export function createDecisionThreadHash(threadId: string | null): string {
  return threadId === null ? "#/threads" : `#/threads?thread_id=${encodeURIComponent(threadId)}`;
}

export function DecisionThreadsPage({
  selectedThreadId,
  onSelectThread,
}: {
  readonly selectedThreadId: string | null;
  readonly onSelectThread: (threadId: string | null) => void;
}): JSX.Element {
  const threads = useDecisionThreads(selectedThreadId);
  const scenarios = useScenarios();
  const cohorts = useCohorts();
  const experiments = useSemanticExperiments();
  const [scenarioId, setScenarioId] = useState("");
  const [cohortId, setCohortId] = useState("");
  const [experimentId, setExperimentId] = useState("");
  const [submitError, setSubmitError] = useState<Error | null>(null);
  const selectedScenario = scenarios.state.data?.items.find((item) => item.id === scenarioId) ?? null;
  const compatibleExperiments = useMemo(
    () => (experiments.state.data?.items ?? []).filter(
      (item) => item.scenario.id === scenarioId && (cohortId === "" || item.cohort.id === cohortId),
    ),
    [cohortId, experiments.state.data, scenarioId],
  );
  const context: DecisionThreadContextRequest | null = selectedScenario === null ? null : {
    world_model_id: selectedScenario.snapshot.world_model_id,
    world_snapshot_id: selectedScenario.snapshot.world_snapshot_id,
    scenario_id: selectedScenario.id,
    cohort_id: cohortId === "" ? null : cohortId,
    semantic_experiment_id: experimentId === "" ? null : experimentId,
  };
  const selectedDetail = threads.detail.data?.id === selectedThreadId ? threads.detail.data : null;

  const resetDownstream = (nextScenarioId: string): void => {
    setScenarioId(nextScenarioId);
    setCohortId("");
    setExperimentId("");
    setSubmitError(null);
  };

  const submit = async (): Promise<void> => {
    if (context === null || selectedScenario === null) return;
    setSubmitError(null);
    try {
      const result = selectedThreadId === null
        ? await threads.create({
            ...context,
            title: selectedScenario.title,
            decision_question: selectedScenario.decision_question,
          })
        : await threads.append(context);
      if (result !== null) onSelectThread(result.id);
    } catch (error: unknown) {
      setSubmitError(error instanceof Error ? error : new Error("保存决策上下文失败。"));
    }
  };

  return (
    <div className="decision-threads-page">
      <header className="decision-threads-hero">
        <div><span>DECISION PORTFOLIO / PERSISTENT</span><h2>一个决策，一条可恢复的上下文链</h2><p>把冻结现实、Scenario、Cohort、语义实验与报告入口绑定为追加式版本。刷新和切页不再依赖临时选择。</p></div>
        <aside><strong>不可变边界</strong><p>每次推进产生新 revision；旧世界、旧实验和失败结果都会保留，不会被最新状态覆盖。</p></aside>
      </header>

      <div className="decision-threads-layout">
        <aside className="decision-thread-directory" aria-label="决策任务目录">
          <header><strong>决策任务</strong><button type="button" onClick={threads.reload}>刷新</button></header>
          <a href={createDecisionThreadHash(null)} data-selected={selectedThreadId === null} onClick={() => onSelectThread(null)}>＋ 新建决策任务</a>
          {threads.directory.status === "error" ? <ApiErrorPanel title="无法读取决策任务" error={threads.directory.error} isRetrying={false} onRetry={threads.reload} /> : null}
          <ul>{threads.directory.data?.items.map((item) => <li key={item.id}><a href={createDecisionThreadHash(item.id)} data-selected={selectedThreadId === item.id} onClick={() => onSelectThread(item.id)}><strong>{item.title}</strong><span>Revision {item.latest_revision.version}</span><small>{item.decision_question}</small></a></li>)}</ul>
        </aside>

        <main className="decision-thread-stage">
          <header><span>{selectedThreadId === null ? "CREATE / REVISION 1" : "APPEND / NEXT REVISION"}</span><h3>{selectedDetail?.title ?? "选择一条已封存 Scenario 作为决策起点"}</h3>{selectedDetail === null ? null : <p>{selectedDetail.decision_question}</p>}</header>
          <section className="decision-context-composer" aria-label="决策上下文版本编辑器">
            <label htmlFor="decision-thread-scenario">Scenario<select id="decision-thread-scenario" name="decision_thread_scenario" value={scenarioId} onChange={(event) => resetDownstream(event.target.value)}><option value="">选择已封存 Scenario</option>{scenarios.state.data?.items.map((item) => <option key={item.id} value={item.id}>{item.title} · snapshot {item.snapshot.version}</option>)}</select></label>
            <label htmlFor="decision-thread-cohort">Cohort<select id="decision-thread-cohort" name="decision_thread_cohort" value={cohortId} onChange={(event) => { setCohortId(event.target.value); setExperimentId(""); }}><option value="">暂不绑定 Cohort</option>{cohorts.state.data?.items.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.persona_count} personas</option>)}</select></label>
            <label htmlFor="decision-thread-experiment">Semantic Experiment<select id="decision-thread-experiment" name="decision_thread_experiment" value={experimentId} disabled={cohortId === ""} onChange={(event) => setExperimentId(event.target.value)}><option value="">暂不绑定 Experiment</option>{compatibleExperiments.map((item) => <option key={item.id} value={item.id}>{item.status} · {item.variant_count} variants · {item.trial_count} trials</option>)}</select></label>
            {submitError === null ? null : <div className="decision-thread-submit-error" role="alert"><strong>上下文没有保存</strong><p>{submitError.message}</p></div>}
            <button className="button button-primary" type="button" disabled={context === null || threads.submitting} onClick={() => void submit()}>{threads.submitting ? "正在保存…" : selectedThreadId === null ? "创建持久决策任务" : "追加上下文版本"}</button>
          </section>

          {selectedDetail === null ? <div className="decision-thread-empty"><strong>先选择任务或创建第一版</strong><p>系统不会自动打开目录第一项，避免把旧任务误认为当前决策。</p></div> : <ol className="decision-revision-timeline">{[...selectedDetail.revisions].reverse().map((revision) => <li key={revision.id}><header><strong>Revision {revision.version}</strong><time dateTime={revision.created_at}>{new Date(revision.created_at).toLocaleString("zh-CN")}</time></header><dl><div><dt>World Snapshot</dt><dd><code>{shortDigest(revision.snapshot_sha256)}</code></dd></div><div><dt>Scenario</dt><dd><code>{shortDigest(revision.scenario_sha256)}</code></dd></div><div><dt>Cohort</dt><dd><code>{shortDigest(revision.cohort_sha256)}</code></dd></div><div><dt>Experiment / Report</dt><dd><code>{shortDigest(revision.experiment_sha256)}</code>{revision.semantic_experiment_id === null ? null : <a href={`#/reports?experiment_id=${encodeURIComponent(revision.semantic_experiment_id)}`}>打开报告 →</a>}</dd></div></dl></li>)}</ol>}
        </main>

        <aside className="decision-thread-context"><strong>当前持久上下文</strong>{selectedDetail === null ? <p>新任务从一条严格 Scenario 开始。</p> : <dl><div><dt>版本</dt><dd>{selectedDetail.latest_revision.version}</dd></div><div><dt>World</dt><dd>{shortDigest(selectedDetail.latest_revision.snapshot_sha256)}</dd></div><div><dt>Scenario</dt><dd>{shortDigest(selectedDetail.latest_revision.scenario_sha256)}</dd></div><div><dt>Cohort</dt><dd>{shortDigest(selectedDetail.latest_revision.cohort_sha256)}</dd></div><div><dt>Experiment</dt><dd>{shortDigest(selectedDetail.latest_revision.experiment_sha256)}</dd></div></dl>}</aside>
      </div>
    </div>
  );
}
